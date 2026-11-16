// "For you" (rolepage.render_me, Janis 16.11.2026): the user's own work. Add and change with one dialog, mark as done
// with a note of what was done (the same dialog changes the note later), open again, delete after a confirmation.
// Everything is sent with fetch; afterwards only the list, its count and the badge at the station are swapped. Needs core.js.
(function () {
  "use strict";
  var tile = document.getElementById("todos");
  var dialog = document.getElementById("todo-dialog");
  var doneDialog = document.getElementById("todo-done-dialog");
  var confirmDialog = document.getElementById("todo-confirm");
  var project = document.querySelector(".project");
  if (!tile || !dialog || !doneDialog || !confirmDialog || !project) return;
  var form = dialog.querySelector("form");
  var textInput = form.querySelector('input[name="text"]');
  var doneForm = doneDialog.querySelector("form");
  var noteInput = doneForm.querySelector('textarea[name="note"]');
  var pendingId = null;

  function refresh() {
    return AgentHub.swap(["me-list", "me-count", "me-badge"]).catch(function () { AgentHub.reload(); });
  }
  function post(url, body) {
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(refresh, refresh);
  }

  function openText(action, text, edit) {
    form.action = action;
    document.getElementById("todo-dialog-title").textContent = dialog.dataset[edit ? "titleEdit" : "titleNew"];
    document.getElementById("todo-dialog-button").textContent = dialog.dataset[edit ? "btnEdit" : "btnNew"];
    textInput.value = text || "";
    dialog.showModal();
    textInput.focus();
    textInput.select();
  }

  function openNote(row) {
    doneForm.action = "/todos/" + row.dataset.id + "/done";
    noteInput.value = row.querySelector(".todo-raw").value;
    doneDialog.showModal();
    noteInput.focus();
  }

  [dialog, doneDialog].forEach(function (d) {
    d.addEventListener("close", function () { var f = d.querySelector("form"); f.reset(); AgentHub.clear(f); });
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!AgentHub.validate(form)) return;
    var body = new FormData(form);
    dialog.close();
    post(form.action, body);
  });

  doneForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var body = new FormData(doneForm);
    doneDialog.close();
    post(doneForm.action, body);
  });

  tile.addEventListener("click", function (event) {   // on the tile: its list is swapped, the tile stays
    if (event.target.closest("#todo-add")) { openText("/projects/" + project.dataset.id + "/todos", "", false); return; }
    var button = event.target.closest("[data-todo]");
    if (!button) return;
    var row = button.closest(".todo-row");
    var action = button.dataset.todo;
    if (action === "edit") openText("/todos/" + row.dataset.id + "/edit", row.querySelector(".check-title").textContent, true);
    else if (action === "done" || action === "note") openNote(row);
    else if (action === "reopen") post("/todos/" + row.dataset.id + "/reopen");
    else if (action === "delete") { pendingId = row.dataset.id; confirmDialog.showModal(); }
  });

  document.getElementById("todo-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    confirmDialog.close();
    if (id) post("/todos/" + id + "/delete");
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
