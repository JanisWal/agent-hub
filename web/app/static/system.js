// System page (owner): restart or shut down the Pi. Each action has its own dialog with the owner's
// password; on success the dialog closes and a note says what happens now (texts come from the server).
(function () {
  var root = document.querySelector(".sys-wrap");
  if (!root) return;
  var note = document.getElementById("sys-power-note");

  function wire(action) {
    var dialog = document.getElementById("power-" + action + "-dialog");
    var form = dialog.querySelector("form");
    var error = dialog.querySelector("[data-error]");

    function show(text) {
      error.textContent = text || root.dataset.network;
      error.hidden = false;
    }

    dialog.addEventListener("close", function () {
      form.reset();
      AgentHub.clear(form);
      error.hidden = true;
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!AgentHub.validate(form)) return;
      error.hidden = true;
      fetch(form.dataset.url, { method: "POST", body: new FormData(form) })
        .then(function (response) {
          if (response.ok) {
            dialog.close();
            note.textContent = note.dataset["done" + action.charAt(0).toUpperCase() + action.slice(1)];
            note.hidden = false;
            root.querySelectorAll("[data-power]").forEach(function (button) { button.disabled = true; });
            return;
          }
          return response.json().then(function (data) { show(data.message); }, function () { show(""); });
        })
        .catch(function () { show(""); });
    });
    return dialog;
  }

  // Manual backup: no dialog (it harms nothing). The button asks the hub to start it, then we ask every two
  // seconds how it is going until it is over (the runner reports the result; the nightly backup is the same job).
  var backupButton = root.querySelector("[data-backup]");
  var backupNote = document.getElementById("sys-backup-note");

  function backupShow(kind) {
    backupNote.textContent = backupNote.dataset[kind];
    backupNote.hidden = false;
  }

  function backupFinished(kind) {
    backupShow(kind);
    backupButton.disabled = false;
  }

  function backupPoll(tries) {
    fetch("/system/backup")
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.state === "running" && tries < 150) setTimeout(function () { backupPoll(tries + 1); }, 2000);
        else backupFinished(data.state === "ok" ? "ok" : "failed");
      })
      .catch(function () { backupFinished("failed"); });
  }

  backupButton.addEventListener("click", function () {
    backupButton.disabled = true;
    backupShow("running");
    var body = new FormData();
    body.append("action", "backup");
    fetch("/system/power", { method: "POST", body: body })
      .then(function (response) {
        if (!response.ok) { backupFinished("failed"); return; }
        backupPoll(0);
      })
      .catch(function () { backupFinished("failed"); });
  });

  var dialogs = { reboot: wire("reboot"), poweroff: wire("poweroff") };
  root.addEventListener("click", function (event) {
    var button = event.target.closest("[data-power]");
    if (button) dialogs[button.dataset.power].showModal();
  });
})();
