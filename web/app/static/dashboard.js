// Behaviour of the logged-in pages: greeting, settings drawer, dialogs, project pages and drag and drop.
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

  // Pages of project tiles. Only the current page is visible. Dragging a tile works like
  // on a phone's home screen: hold it at the left or right edge to turn the page, and
  // past the last page a new page opens. Empty slots and the "+" tile never move.
  var pagesBox = $("#pages");
  if (pagesBox) {
    var SIZE = Number(pagesBox.dataset.size);
    var pager = $("#pager");
    var edges = document.querySelectorAll(".edge");
    var ARROWS = {
      left: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-8 6 8 6z"/></svg>',
      right: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l8 6-8 6z"/></svg>'
    };
    var dragged = null;
    var startGrid = null;
    var before = "";
    var flipTimer = null;
    var flipDir = 0;

    var grids = function () { return Array.prototype.slice.call(pagesBox.querySelectorAll(".grid")); };
    var tilesOf = function (grid) { return Array.prototype.slice.call(grid.querySelectorAll(".tile[data-id]")); };
    var current = function () {
      var all = grids();
      for (var i = 0; i < all.length; i++) if (!all[i].hidden) return i + 1;
      return 1;
    };
    var order = function () {
      var ids = [];
      grids().forEach(function (grid) { tilesOf(grid).forEach(function (t) { ids.push(t.dataset.id); }); });
      return ids.join();
    };

    function arrowElement(target, count, side, label) {
      var element;
      if (target >= 1 && target <= count) {
        element = document.createElement("a");
        element.className = "pager-arrow";
        element.href = "/?page=" + target;
        element.dataset.page = target;
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
      var now = current();
      var texts = pager.dataset;
      pager.hidden = count < 2;
      pager.textContent = "";
      pager.appendChild(arrowElement(now - 1, count, "left", texts.labelPrev));
      var dots = document.createElement("span");
      dots.className = "dots";
      for (var n = 1; n <= count; n++) {
        var dot = document.createElement("a");
        dot.className = "dot" + (n === now ? " active" : "");
        dot.href = "/?page=" + n;
        dot.dataset.page = n;
        dot.setAttribute("aria-label", texts.labelPage.replace("{n}", n));
        if (n === now) dot.setAttribute("aria-current", "page");
        dots.appendChild(dot);
      }
      pager.appendChild(dots);
      pager.appendChild(arrowElement(now + 1, count, "right", texts.labelNext));
    }

    function showPage(n) {
      var all = grids();
      n = Math.min(Math.max(n, 1), all.length);
      all.forEach(function (grid, i) { grid.hidden = i + 1 !== n; });
      try { history.replaceState(null, "", "/?page=" + n); } catch (e) {}
      renderPager();
    }

    pager.addEventListener("click", function (event) {
      var link = event.target.closest("[data-page]");
      if (!link) return;
      event.preventDefault();
      showPage(Number(link.dataset.page));
    });

    // Turn the page after the pointer rested at an edge for a moment.
    function flip() {
      var dir = flipDir;
      flipDir = 0;  // lets the next dragover arm the timer again
      var all = grids();
      var target = current() + dir;
      if (target < 1) return;
      if (target > all.length) {
        // A new page only opens if the last page holds a project besides the dragged one.
        var others = tilesOf(all[all.length - 1]).filter(function (t) { return t !== dragged; });
        if (!others.length) return;
        var fresh = document.createElement("div");
        fresh.className = "grid";
        fresh.hidden = true;
        pagesBox.appendChild(fresh);
      }
      showPage(target);
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

    document.addEventListener("dragstart", function (event) {
      var tile = event.target.closest && event.target.closest(".tile[data-id]");
      if (!tile) return;
      dragged = tile;
      startGrid = tile.closest(".grid");
      before = order();
      tile.classList.add("dragging");
      document.body.classList.add("dragging-tile");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", tile.dataset.id);
    });

    document.addEventListener("dragover", function (event) {
      if (!dragged) return;
      event.preventDefault();
      checkEdges(event.clientX);
      var grid = pagesBox.querySelector(".grid:not([hidden])");
      if (!grid || !grid.contains(event.target)) return;
      var over = event.target.closest(".tile[data-id]");
      if (over && over !== dragged) {
        if (dragged.parentNode !== grid) {
          grid.insertBefore(dragged, over);  // arrived from another page: take this slot
        } else {
          var kids = Array.prototype.slice.call(grid.children);
          if (kids.indexOf(dragged) < kids.indexOf(over)) over.after(dragged);
          else over.before(dragged);
        }
      } else if (!over && (event.target.closest(".tile.plus, .tile.ghost") || dragged.parentNode !== grid)) {
        // On a free slot (or an empty page): go behind the last project of this page.
        var others = tilesOf(grid).filter(function (t) { return t !== dragged; });
        var last = others[others.length - 1];
        var anchor = last ? last.nextSibling : grid.firstChild;
        if (anchor !== dragged) grid.insertBefore(dragged, anchor);
      }
    });

    document.addEventListener("drop", function (event) { if (dragged) event.preventDefault(); });

    document.addEventListener("dragend", function () {
      if (!dragged) return;
      var tile = dragged;
      dragged = null;
      tile.classList.remove("dragging");
      document.body.classList.remove("dragging-tile");
      clearTimeout(flipTimer);
      flipDir = 0;
      Array.prototype.forEach.call(edges, function (edge) { edge.classList.remove("hot"); });

      // A page we opened but did not use disappears again.
      grids().forEach(function (grid) { if (!grid.querySelector(".tile")) grid.remove(); });
      var endGrid = tile.closest(".grid");
      var all = grids();
      showPage(all.indexOf(endGrid) + 1);

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
    });
  }
})();
