// Kanban board of a project: add and edit items, accept/reject suggestions, trash, dragging.
// Needs core.js, motion.js and sortable.js.
(function () {
  var project = document.querySelector(".project");
  if (!project) return;
  var projectId = project.dataset.id;

  function $(selector, root) { return (root || document).querySelector(selector); }
  function cards() { return Array.prototype.slice.call(document.querySelectorAll("#board .card")); }
  // Only the board and the trash/archive change (no reload, a running upload goes on); if that fails, the page reloads.
  // Janis, 19.11.2026 ("like the user list"): every card glides from where it was to its new place (FLIP), a new one
  // fades in, and a context that was unfolded stays unfolded.
  function reload(quietly) {
    var before = {}, open = {};
    cards().forEach(function (card) {
      before[card.dataset.id] = card.getBoundingClientRect();
      if (card.querySelector(".card-title.open")) open[card.dataset.id] = true;
    });
    return AgentHub.swap(["board", "board-state", "vault"]).then(function (fresh) {
      if (quietly && !fresh.changed.length) return;   // a look that found nothing new does nothing
      setView(currentView, false);
      refreshCounts();
      cards().forEach(function (card) {
        if (open[card.dataset.id]) {
          var title = card.querySelector(".card-title.has-details");
          if (title) { title.classList.add("open"); title.querySelector(".card-details").hidden = false; }
        }
        var was = before[card.dataset.id];
        if (!was) { appear(card); return; }
        var now = card.getBoundingClientRect();
        glide(card, was.left - now.left, was.top - now.top);
      });
    }).catch(function () { if (!quietly) AgentHub.reload(); });
  }
  function glide(card, dx, dy) {
    if (Motion.reduced() || (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5)) return;
    var x = Motion.spring(dx, Motion.MOVE, move), y = Motion.spring(dy, Motion.MOVE, move);
    function move() { card.style.transform = x.value || y.value ? "translate3d(" + x.value + "px," + y.value + "px,0)" : ""; }
    move(); x.to(0); y.to(0);
  }
  function appear(card) {
    if (Motion.reduced()) return;
    var p = Motion.spring(0, Motion.MOVE, function (v) {
      card.style.opacity = String(v);
      card.style.transform = v < 0.999 ? "scale(" + (0.96 + 0.04 * v) + ")" : "";
    }, 0.002);
    p.to(1);
  }
  // A card that leaves (trash, rejected, deleted for good) shrinks and fades first; the others glide up after it.
  function leave(card) {
    return new Promise(function (resolve) {
      if (!card || Motion.reduced()) { resolve(); return; }
      var p = Motion.spring(1, Motion.MOVE, function (v) {
        card.style.opacity = String(Math.max(0, v));
        card.style.transform = "scale(" + (0.94 + 0.06 * v) + ")";
      }, 0.002);
      p.to(0);
      setTimeout(resolve, 220);
    });
  }
  function post(url) { return fetch(url, { method: "POST" }); }

  // Add and rename items with the same dialog.
  var itemDialog = $("#item-dialog");
  var itemForm = $("form", itemDialog);
  var titleInput = $('input[name="title"]', itemDialog);
  var detailsInput = $('textarea[name="details"]', itemDialog);

  function openItemDialog(options) {
    itemForm.action = options.action;
    $('input[name="kind"]', itemDialog).value = options.kind || "bug";
    $("#item-dialog-title").textContent = itemDialog.dataset[options.edit ? "titleEdit" : "titleNew"];
    $("#item-dialog-button").textContent = itemDialog.dataset[options.edit ? "btnEdit" : "btnNew"];
    titleInput.value = options.title || "";
    detailsInput.value = options.details || "";
    itemDialog.showModal();
    titleInput.focus();
    titleInput.select();
  }

  itemForm.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!AgentHub.validate(itemForm)) return;
    var body = new FormData(itemForm);
    itemDialog.close();
    fetch(itemForm.action, { method: "POST", body: body, credentials: "same-origin" }).then(reload, reload);
  });

  itemDialog.addEventListener("close", function () {
    itemForm.reset();
    AgentHub.clear(itemForm);
  });

  document.addEventListener("click", function (event) {
    var add = event.target.closest(".add");
    if (add) openItemDialog({ action: "/projects/" + projectId + "/items", kind: add.dataset.kind });
  });

  // A click on a bullet unfolds the context behind it (Janis, 19.11.2026); a double click renames it.
  document.addEventListener("click", function (event) {
    var title = event.target.closest(".card .card-title.has-details");
    if (!title || event.target.closest(".info-dot")) return;
    var more = title.querySelector(".card-details");
    more.hidden = !more.hidden;
    title.classList.toggle("open", !more.hidden);
  });

  document.addEventListener("dblclick", function (event) {
    var title = event.target.closest(".card .card-title");
    if (!title) return;
    var card = title.closest(".card");
    openItemDialog({
      action: "/items/" + card.dataset.id,
      kind: card.closest(".column").dataset.kind,
      title: (title.querySelector(".card-text") || title).textContent,
      details: (title.querySelector(".card-details") || { textContent: "" }).textContent,
      edit: true
    });
  });

  // Confirm before anything is deleted for good (single "Ja / Abbrechen", no password).
  var confirmDialog = $("#confirm-dialog");
  var pending = null;
  function confirmThen(messageKey, action) {
    $("#confirm-text").textContent = confirmDialog.dataset[messageKey];
    pending = action;
    confirmDialog.showModal();
  }
  $("#confirm-yes").addEventListener("click", function () {
    confirmDialog.close();
    if (pending) pending();
  });
  confirmDialog.addEventListener("close", function () { pending = null; });

  // Card and trash buttons: accept, reject, discard, restore, delete.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-action]");
    if (!button) return;
    var holder = button.closest("[data-id]");
    var id = holder.dataset.id;
    var url = "/items/" + id + "/" + button.dataset.action;
    var leaves = ["discard", "reject", "delete", "restore"].indexOf(button.dataset.action) >= 0;
    var run = function () {
      var sent = post(url);
      (leaves ? leave(holder) : Promise.resolve()).then(function () { return sent; }).then(reload).catch(reload);
    };
    if (button.dataset.action === "delete") confirmThen("msgItem", run);
    else run();
  });

  document.addEventListener("click", function (event) {   // the trash is swapped: listen on the page, not the button
    if (!event.target.closest("#trash-empty")) return;
    confirmThen("msgEmpty", function () {
      post("/projects/" + projectId + "/trash/empty").then(reload).catch(reload);
    });
  });

  // Trash and archive: two buttons next to the gear (the same behaviour for both) swap the board for
  // that list; the same button again brings the board back. The view survives our own reloads, so
  // restoring several items does not close it each time.
  var vault = $("#vault");
  var board = $("#board");
  var toggles = document.querySelectorAll('.drawer-extra[aria-controls="vault"]');   // the Manager's pair: mvault.js
  var currentView = "";
  function setView(view, animate) {
    currentView = view;
    vault.hidden = !view;
    board.hidden = !!view;
    Array.prototype.forEach.call(vault.querySelectorAll(".vault-view"), function (part) {
      part.hidden = part.dataset.view !== view;
    });
    Array.prototype.forEach.call(toggles, function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    });
    var shown = view ? vault : board;
    if (animate) {   // a short fade, restarted each time
      shown.classList.remove("appear");
      void shown.offsetWidth;
      shown.classList.add("appear");
    }
    try { sessionStorage.setItem("vault:" + projectId, view); } catch (e) {}
  }
  try { setView(sessionStorage.getItem("vault:" + projectId) || "", false); } catch (e) { setView("", false); }
  Array.prototype.forEach.call(toggles, function (button) {
    button.addEventListener("click", function () {
      setView(currentView === button.dataset.view ? "" : button.dataset.view, true);
    });
  });

  // Dragging: agreed items move within and between columns (mouse, pen or finger).
  // Suggestions stay put until they are accepted.
  var snapshot = "";

  function layout() {
    return JSON.stringify(Array.prototype.map.call(document.querySelectorAll(".open-list"), function (list) {
      return Array.prototype.map.call(list.querySelectorAll(".card:not(.proposed)"), function (card) { return card.dataset.id; });
    }));
  }

  // Keep the number badges of the columns right after a card moved.
  function refreshCounts() {
    Array.prototype.forEach.call(document.querySelectorAll(".column"), function (column) {
      $(".count", column).textContent = column.querySelectorAll(".card").length;
    });
  }

  Motion.sortable({   // suggestions stand in the list but stay put until they are accepted
    itemSelector: ".open-list .card:not(.proposed)",
    items: function () { return document.querySelectorAll(".open-list .card:not(.proposed)"); },
    containerFor: function (el) {
      var column = el.closest(".column");
      return column && column.querySelector(".open-list");
    },
    axis: "y",
    gapHost: function (card) { return card.closest(".open-list"); },
    ignore: ".card-btn",
    onPick: function () { snapshot = layout(); },
    onDrop: function (info) {
      refreshCounts();
      if (layout() === snapshot) return;
      var list = info.item.closest(".open-list");
      var ids = Array.prototype.map.call(list.querySelectorAll(".card:not(.proposed)"), function (c) { return c.dataset.id; });
      fetch("/items/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: list.dataset.kind, ids: ids })
      }).then(function (response) {
        if (!response.ok) reload();
      }).catch(reload);
    }
  });

  // While a task is on its way (the line above the board) or items wait in the queue, the board looks again every few
  // seconds and swaps in what changed (Janis, 19.11.2026: "I do not see that he works"; 22.11.2026: an item leaves the
  // board when the programmer takes it); not while dragging, typing or the tab is hidden.
  // Through the page's one timer (core.js): the swap leaves the board alone when nothing changed, and lets cards glide
  // when something did; a failed look waits for the next one instead of reloading the page.
  var watch = AgentHub.live({
    every: 4000,
    when: function () {
      return !!board.offsetParent && !!(   // only while the board can be seen (another tab: its own parts)
        document.querySelector("#board-state [data-live]") || document.querySelector("#board .card:not(.proposed)"));
    },
    run: function () { return reload(true); },
  });
  document.addEventListener("agenthub:view", function () { watch.soon(); });   // back on the board: look at once
})();
