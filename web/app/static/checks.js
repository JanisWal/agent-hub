// Regular checks in the Manager view: add and edit with one dialog (the pencil, or a double click on a check),
// delete after a confirmation. A daily check shows seven weekday circles (all ticked at first). In the edit
// dialog a link marks the check as done. Needs core.js.
(function () {
  var dialog = document.getElementById("check-dialog");
  var tile = document.getElementById("checks");
  var project = document.querySelector(".project");
  if (!dialog || !tile || !project) return;
  var projectId = project.dataset.id;
  var form = dialog.querySelector("form");
  var textInput = form.querySelector('input[name="text"]');
  var cycleSelect = form.querySelector('select[name="cycle"]');
  var daysBox = document.getElementById("check-days");
  var dayInputs = daysBox.querySelectorAll('input[name="day"]');
  var daysError = document.getElementById("check-days-error");
  var doneLink = document.getElementById("check-dialog-done");
  var confirmDialog = document.getElementById("check-confirm");
  var pendingId = null;
  var editingId = null;

  function reload() { AgentHub.reload(); }

  // The weekday circles only exist for a daily check.
  function syncDays() { daysBox.hidden = cycleSelect.value !== "daily"; }
  function anyDay() { return Array.prototype.some.call(dayInputs, function (box) { return box.checked; }); }
  function setDays(days) {
    dayInputs.forEach(function (box, n) { box.checked = (days || "1111111").charAt(n) === "1"; });
  }

  function openDialog(options) {
    form.action = options.action;
    document.getElementById("check-dialog-title").textContent = dialog.dataset[options.edit ? "titleEdit" : "titleNew"];
    document.getElementById("check-dialog-button").textContent = dialog.dataset[options.edit ? "btnEdit" : "btnNew"];
    textInput.value = options.text || "";
    cycleSelect.value = options.cycle || "weekly";
    setDays(options.days);
    editingId = options.edit ? options.id : null;
    doneLink.hidden = !options.edit;
    daysError.hidden = true;
    syncDays();
    dialog.showModal();
    textInput.focus();
    textInput.select();
  }

  function openFor(row) {
    openDialog({
      action: "/checks/" + row.dataset.id, text: row.querySelector(".check-title").textContent,
      cycle: row.dataset.cycle, days: row.dataset.days, edit: true, id: row.dataset.id,
    });
  }

  dialog.addEventListener("close", function () {
    form.reset();
    AgentHub.clear(form);
    daysError.hidden = true;
    editingId = null;
  });

  cycleSelect.addEventListener("change", syncDays);
  daysBox.addEventListener("change", function () { if (anyDay()) daysError.hidden = true; });

  form.addEventListener("submit", function (event) {
    if (cycleSelect.value === "daily" && !anyDay()) {   // a daily check needs at least one day
      event.preventDefault();
      daysError.hidden = false;
    }
  });

  doneLink.addEventListener("click", function () {
    var id = editingId;
    dialog.close();
    if (id) fetch("/checks/" + id + "/done", { method: "POST" }).then(reload).catch(reload);
  });

  document.getElementById("check-add").addEventListener("click", function () {
    openDialog({ action: "/projects/" + projectId + "/checks" });
  });

  tile.addEventListener("dblclick", function (event) {
    var title = event.target.closest(".check-title");
    if (title) openFor(title.closest(".check-row"));
  });

  tile.addEventListener("click", function (event) {
    var button = event.target.closest("[data-check]");
    if (!button) return;
    var row = button.closest(".check-row");
    if (button.dataset.check === "edit") {
      openFor(row);
    } else {
      pendingId = row.dataset.id;
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
