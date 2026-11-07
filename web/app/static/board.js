// Kanban board of a project: add and edit items, accept/reject suggestions, trash, drag and drop.
(function () {
  var project = document.querySelector(".project");
  if (!project) return;
  var projectId = project.dataset.id;

  function $(selector, root) { return (root || document).querySelector(selector); }
  function reload() {
    try { sessionStorage.setItem("noanim", "1"); } catch (e) {}  // no entrance animation again
    location.reload();
  }
  function post(url) { return fetch(url, { method: "POST" }); }

  // Add and rename items with the same dialog.
  var itemDialog = $("#item-dialog");
  var itemForm = $("form", itemDialog);
  var titleInput = $('input[name="title"]', itemDialog);

  function openItemDialog(options) {
    itemForm.action = options.action;
    $('input[name="kind"]', itemDialog).value = options.kind || "bug";
    $("#item-dialog-title").textContent = itemDialog.dataset[options.edit ? "titleEdit" : "titleNew"];
    $("#item-dialog-button").textContent = itemDialog.dataset[options.edit ? "btnEdit" : "btnNew"];
    titleInput.value = options.title || "";
    itemDialog.showModal();
    titleInput.focus();
    titleInput.select();
  }

  itemDialog.addEventListener("close", function () {
    itemForm.reset();
    AgentHub.clear(itemForm);
  });

  document.addEventListener("click", function (event) {
    var add = event.target.closest(".add");
    if (add) openItemDialog({ action: "/projects/" + projectId + "/items", kind: add.dataset.kind });
  });

  document.addEventListener("dblclick", function (event) {
    var title = event.target.closest(".card .card-title");
    if (!title) return;
    var card = title.closest(".card");
    openItemDialog({
      action: "/items/" + card.dataset.id,
      kind: card.closest(".column").dataset.kind,
      title: title.textContent,
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
    var id = button.closest("[data-id]").dataset.id;
    var url = "/items/" + id + "/" + button.dataset.action;
    var run = function () { post(url).then(reload).catch(reload); };
    if (button.dataset.action === "delete") confirmThen("msgItem", run);
    else run();
  });

  var emptyButton = $("#trash-empty");
  if (emptyButton) {
    emptyButton.addEventListener("click", function () {
      confirmThen("msgEmpty", function () {
        post("/projects/" + projectId + "/trash/empty").then(reload).catch(reload);
      });
    });
  }

  // Trash opens and closes with its button.
  // The state survives our own reloads, so restoring several items does not close it each time.
  var trash = $("#trash");
  var trashToggle = $("#trash-toggle");
  function setTrashOpen(open) {
    trash.hidden = !open;
    trashToggle.setAttribute("aria-expanded", String(open));
    try { sessionStorage.setItem("trashOpen:" + projectId, open ? "1" : ""); } catch (e) {}
  }
  try { if (sessionStorage.getItem("trashOpen:" + projectId)) setTrashOpen(true); } catch (e) {}
  trashToggle.addEventListener("click", function () { setTrashOpen(trash.hidden); });

  // Drag and drop: agreed items move within and between columns. Suggestions stay put.
  var dragged = null;
  var snapshot = "";

  function layout() {
    return JSON.stringify(Array.prototype.map.call(document.querySelectorAll(".open-list"), function (list) {
      return Array.prototype.map.call(list.querySelectorAll(".card"), function (card) { return card.dataset.id; });
    }));
  }

  document.addEventListener("dragstart", function (event) {
    var card = event.target.closest && event.target.closest(".card[draggable]");
    if (!card) return;
    dragged = card;
    snapshot = layout();
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.id);
  });

  document.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var list = event.target.closest(".column") && event.target.closest(".column").querySelector(".open-list");
    if (!list) return;
    event.preventDefault();
    // Insert before the first card whose middle is below the pointer, else at the end.
    var cards = Array.prototype.filter.call(list.querySelectorAll(".card"), function (c) { return c !== dragged; });
    var next = null;
    for (var i = 0; i < cards.length; i++) {
      var box = cards[i].getBoundingClientRect();
      if (event.clientY < box.top + box.height / 2) { next = cards[i]; break; }
    }
    if (next) { if (dragged.nextSibling !== next) list.insertBefore(dragged, next); }
    else if (list.lastElementChild !== dragged) list.appendChild(dragged);
  });

  document.addEventListener("drop", function (event) { if (dragged) event.preventDefault(); });

  document.addEventListener("dragend", function () {
    if (!dragged) return;
    var card = dragged;
    dragged = null;
    card.classList.remove("dragging");
    if (layout() === snapshot) return;
    var list = card.closest(".open-list");
    var ids = Array.prototype.map.call(list.querySelectorAll(".card"), function (c) { return c.dataset.id; });
    fetch("/items/reorder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: list.dataset.kind, ids: ids })
    }).then(function (response) {
      if (!response.ok) reload();
      else refreshCounts();
    }).catch(reload);
  });

  // Keep the number badges of the columns right after a card moved.
  function refreshCounts() {
    Array.prototype.forEach.call(document.querySelectorAll(".column"), function (column) {
      $(".count", column).textContent = column.querySelectorAll(".card").length;
    });
  }
})();
