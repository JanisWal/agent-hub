// System page (owner): restart or shut down the Pi, a manual backup, and how uploads are cut. Each power action has its
// own dialog with the owner's password; on success the dialog closes and a note says what happens now (texts come from
// the server).
(function () {
  var root = document.querySelector(".sys-wrap");
  if (!root) return;
  var note = document.getElementById("sys-power-note");

  // Live numbers (sysstats.py): the bars take their share from data-pct at first, then the server's figures every few
  // seconds while the page is visible (AgentHub.live pauses when it is hidden or a dialog is open).
  var stats = document.getElementById("sys-stats");
  function paint(items) {
    items.forEach(function (item) {
      var cell = stats.querySelector('[data-key="' + item.key + '"]');
      if (!cell) return;
      cell.dataset.level = item.level;
      cell.querySelector(".sys-val").textContent = item.text;
      cell.querySelector(".sys-bar > i").style.transform = "scaleX(" + Math.max(0, Math.min(1, item.pct / 100)) + ")";
    });
  }
  if (stats) {
    paint(Array.prototype.map.call(stats.querySelectorAll(".sys-meter"), function (cell) {
      return { key: cell.dataset.key, level: cell.dataset.level, pct: Number(cell.dataset.pct), text: cell.querySelector(".sys-val").textContent };
    }));
    AgentHub.live({
      every: 3000,
      run: function () {
        return fetch(stats.dataset.url, { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) { if (data && data.ok) paint(data.items); });
      },
    });
  }

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

  // Server settings (upload, AI runs at once): saved as soon as a choice changes (all values of the row together);
  // a failure says so below the list.
  var uploadNote = document.getElementById("sys-upload-note");
  root.querySelectorAll(".sys-upload").forEach(function (row) {
    row.addEventListener("change", function () {
      var body = new FormData();
      row.querySelectorAll("select").forEach(function (select) { body.append(select.name, select.value); });
      uploadNote.hidden = true;
      fetch(row.dataset.url, { method: "POST", body: body })
        .then(function (response) { if (!response.ok) throw new Error(); })
        .catch(function () { uploadNote.textContent = uploadNote.dataset.failed; uploadNote.hidden = false; });
    });
  });

  // Listed addresses (netaddresses.py, only the owner): the list comes back from the server after each change and is
  // swapped in place; a wrong field says so above the buttons.
  var addrDialog = document.getElementById("addresses-dialog");
  var addrOpen = root.querySelector("[data-addresses]");
  if (addrDialog && addrOpen) {
    var addrForm = document.getElementById("addr-form");
    var addrList = document.getElementById("addr-list");
    var addrError = addrForm.querySelector("[data-error]");
    var addrSay = function (text) { addrError.textContent = text || ""; addrError.hidden = !text; };
    var addrSend = function (url, body) {
      return fetch(url, { method: "POST", body: body || null })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.ok) { addrSay(addrForm.dataset[data.field] || addrForm.dataset.failed); return false; }
          addrList.innerHTML = data.list;   // rendered and escaped by the server (systempage.address_list)
          addrSay("");
          return true;
        })
        .catch(function () { addrSay(addrForm.dataset.failed); return false; });
    };
    addrOpen.addEventListener("click", function () { addrSay(""); addrDialog.showModal(); });
    addrForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!window.AgentHub.validate(addrForm)) return;
      addrSend("/system/addresses", new FormData(addrForm)).then(function (done) { if (done) addrForm.reset(); });
    });
    addrList.addEventListener("click", function (event) {
      var remove = event.target.closest("[data-addr-remove]");
      if (!remove) return;
      remove.disabled = true;
      addrSend("/system/addresses/" + remove.dataset.addrRemove + "/remove");
    });
  }

  var dialogs = { reboot: wire("reboot"), poweroff: wire("poweroff") };
  root.addEventListener("click", function (event) {
    var button = event.target.closest("[data-power]");
    if (button) dialogs[button.dataset.power].showModal();
  });
})();
