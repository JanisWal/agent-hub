// Regular checks in the Manager view: add and edit with one dialog (double click on a check edits it),
// mark as done, delete after a confirmation. Needs core.js.
(function () {
  var dialog = document.getElementById("check-dialog");
  var tile = document.getElementById("checks");
  var project = document.querySelector(".project");
  if (!dialog || !tile || !project) return;
  var projectId = project.dataset.id;
  var form = dialog.querySelector("form");
  var textInput = form.querySelector('input[name="text"]');
  var cycleSelect = form.querySelector('select[name="cycle"]');
  var confirmDialog = document.getElementById("check-confirm");
  var pendingId = null;

  function reload() { AgentHub.reload(); }

  function openDialog(options) {
    form.action = options.action;
    document.getElementById("check-dialog-title").textContent = dialog.dataset[options.edit ? "titleEdit" : "titleNew"];
    document.getElementById("check-dialog-button").textContent = dialog.dataset[options.edit ? "btnEdit" : "btnNew"];
    textInput.value = options.text || "";
    cycleSelect.value = options.cycle || "weekly";
    dialog.showModal();
    textInput.focus();
    textInput.select();
  }

  dialog.addEventListener("close", function () {
    form.reset();
    AgentHub.clear(form);
  });

  document.getElementById("check-add").addEventListener("click", function () {
    openDialog({ action: "/projects/" + projectId + "/checks" });
  });

  tile.addEventListener("dblclick", function (event) {
    var title = event.target.closest(".check-title");
    if (!title) return;
    var row = title.closest(".check-row");
    openDialog({ action: "/checks/" + row.dataset.id, text: title.textContent, cycle: row.dataset.cycle, edit: true });
  });

  tile.addEventListener("click", function (event) {
    var button = event.target.closest("[data-check]");
    if (!button) return;
    var id = button.closest(".check-row").dataset.id;
    if (button.dataset.check === "done") {
      fetch("/checks/" + id + "/done", { method: "POST" }).then(reload).catch(reload);
    } else {
      pendingId = id;
      confirmDialog.showModal();
    }
  });

  document.getElementById("check-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    confirmDialog.close();
    if (id) fetch("/checks/" + id + "/delete", { method: "POST" }).then(reload).catch(reload);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
