// Kanban board of a project: add and edit items, accept/reject suggestions, trash, dragging.
(function () {
  var project = document.querySelector(".project");
  if (!project) return;
  var projectId = project.dataset.id;

  function $(selector, root) { return (root || document).querySelector(selector); }
  function reload() {
    try {
      sessionStorage.setItem("noanim", "1");  // no entrance animation again
      sessionStorage.setItem("scrollY", String(window.scrollY));  // stay where you were
    } catch (e) {}
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

  // Dragging: agreed items move within and between columns (mouse, pen or finger).
  // Suggestions stay put until they are accepted.
  var snapshot = "";

  function layout() {
    return JSON.stringify(Array.prototype.map.call(document.querySelectorAll(".open-list"), function (list) {
      return Array.prototype.map.call(list.querySelectorAll(".card"), function (card) { return card.dataset.id; });
    }));
  }

  // Keep the number badges of the columns right after a card moved.
  function refreshCounts() {
    Array.prototype.forEach.call(document.querySelectorAll(".column"), function (column) {
      $(".count", column).textContent = column.querySelectorAll(".card").length;
    });
  }

  Motion.sortable({
    itemSelector: ".open-list .card",
    items: function () { return document.querySelectorAll(".open-list .card"); },
    containerFor: function (el) {
      var column = el.closest(".column");
      return column && column.querySelector(".open-list");
    },
    axis: "y",
    ignore: ".card-btn",
    onPick: function () { snapshot = layout(); },
    onDrop: function (info) {
      refreshCounts();
      if (layout() === snapshot) return;
      var list = info.item.closest(".open-list");
      var ids = Array.prototype.map.call(list.querySelectorAll(".card"), function (c) { return c.dataset.id; });
      fetch("/items/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: list.dataset.kind, ids: ids })
      }).then(function (response) {
        if (!response.ok) reload();
      }).catch(reload);
    }
  });
})();
