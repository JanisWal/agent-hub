// Behaviour of the logged-in pages: greeting, settings bar, dialogs, drag and drop.
(function () {
  function $(selector, root) { return (root || document).querySelector(selector); }

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
            try { sessionStorage.setItem("noanim", "1"); } catch (e) {}
            location.reload();
          }
        })
        .catch(function () { wrong.hidden = false; });
    });
  }

  // Drag and drop: only filled project tiles move, "+" and empty slots stay.
  var grid = $("#grid");
  if (grid) {
    var dragged = null;
    var order = function () {
      return Array.prototype.map.call(grid.querySelectorAll(".tile[data-id]"), function (tile) {
        return tile.dataset.id;
      });
    };
    var before = [];

    grid.addEventListener("dragstart", function (event) {
      var tile = event.target.closest(".tile[data-id]");
      if (!tile) return;
      dragged = tile;
      before = order();
      tile.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", tile.dataset.id);
    });

    grid.addEventListener("dragover", function (event) {
      if (!dragged) return;
      event.preventDefault();
      var over = event.target.closest(".tile[data-id]");
      if (!over || over === dragged) return;
      var tiles = Array.prototype.slice.call(grid.children);
      if (tiles.indexOf(dragged) < tiles.indexOf(over)) over.after(dragged);
      else over.before(dragged);
    });

    grid.addEventListener("drop", function (event) { if (dragged) event.preventDefault(); });

    grid.addEventListener("dragend", function () {
      if (!dragged) return;
      dragged.classList.remove("dragging");
      dragged = null;
      var after = order();
      if (after.join() === before.join()) return;
      fetch("/projects/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: after })
      }).then(function (response) {
        if (!response.ok) location.reload();
      }).catch(function () { location.reload(); });
    });
  }
})();
