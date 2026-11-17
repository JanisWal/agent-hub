// Devices in the Manager view: add and edit with one dialog (the pencil, or a double click on a device), delete after a
// confirmation. The key is only sent, never shown: when a device has one, the dialog says so and an empty field keeps
// it (a tick removes it). Sent with fetch; afterwards only the tile is swapped. Needs core.js.
(function () {
  "use strict";
  var dialog = document.getElementById("device-dialog");
  var tile = document.getElementById("devices");
  var confirmDialog = document.getElementById("device-confirm");
  var project = document.querySelector(".project");
  if (!dialog || !tile || !confirmDialog || !project) return;
  var projectId = project.dataset.id;
  var form = dialog.querySelector("form");
  var keyInput = document.getElementById("device-key");
  var keyState = document.getElementById("device-key-state");
  var removeBox = document.getElementById("device-key-remove-box");
  var errorLine = document.getElementById("device-error");
  var pendingId = null;

  function refresh() { return AgentHub.swap(["devices"]).catch(function () { AgentHub.reload(); }); }

  function showError(code) {
    errorLine.textContent = dialog.dataset["err" + (code ? code.charAt(0).toUpperCase() + code.slice(1) : "Other")] || dialog.dataset.errOther;
    errorLine.hidden = false;
  }

  function openDialog(options) {
    var edit = !!options.edit;
    form.action = options.action;
    document.getElementById("device-dialog-title").textContent = dialog.dataset[edit ? "titleEdit" : "titleNew"];
    document.getElementById("device-dialog-button").textContent = dialog.dataset[edit ? "btnEdit" : "btnNew"];
    form.elements.name.value = options.name || "";
    form.elements.kind.value = options.kind || "other";
    form.elements.kind.dispatchEvent(new Event("change", { bubbles: true }));   // the styled list follows (core.js)
    form.elements.hostname.value = options.hostname || "";
    form.elements.ip.value = options.ip || "";
    form.elements.description.value = options.description || "";
    keyInput.value = "";
    keyInput.placeholder = dialog.dataset[options.hasKey ? "keyEdit" : "keyNew"];
    keyState.hidden = removeBox.hidden = !options.hasKey;
    removeBox.querySelector("input").checked = false;
    errorLine.hidden = true;
    dialog.showModal();
    form.elements.name.focus();
  }

  function openFor(row) {
    openDialog({
      action: "/devices/" + row.dataset.id, edit: true, hasKey: row.dataset.key === "1",
      name: row.dataset.name, kind: row.dataset.kind, hostname: row.dataset.hostname, ip: row.dataset.ip, description: row.dataset.description,
    });
  }

  dialog.addEventListener("close", function () { form.reset(); AgentHub.clear(form); keyInput.value = ""; errorLine.hidden = true; });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!AgentHub.validate(form)) return;
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" })
      .then(function (response) {
        if (response.ok) { dialog.close(); return refresh(); }
        return response.json().then(function (data) { showError(data.error); }, function () { showError(""); });
      }, function () { showError(""); });
  });

  tile.addEventListener("dblclick", function (event) {
    var title = event.target.closest(".check-title");
    if (title) openFor(title.closest(".device-row"));
  });

  tile.addEventListener("click", function (event) {   // on the tile: its content is swapped, the tile stays
    if (event.target.closest("#device-add")) { openDialog({ action: "/projects/" + projectId + "/devices" }); return; }
    var button = event.target.closest("[data-device]");
    if (!button) return;
    var row = button.closest(".device-row");
    if (button.dataset.device === "edit") {
      openFor(row);
    } else {
      pendingId = row.dataset.id;
      confirmDialog.showModal();
    }
  });

  document.getElementById("device-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    confirmDialog.close();
    if (id) fetch("/devices/" + id + "/delete", { method: "POST" }).then(refresh, refresh);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
