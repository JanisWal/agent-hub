// System page (owner): restart or stop the hub, the update, the backup dialog, and how uploads are cut. Each power action has its
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
            back(0);   // only the hub restarts or stops: the gate shows the maintenance page, then the page comes back
            return;
          }
          return response.json().then(function (data) { show(data.message); }, function () { show(""); });
        })
        .catch(function () { show(""); });
    });
    return dialog;
  }

  // The backup (backuppage.py, backup.js does the rest): one dialog with key, time, list and putting one back. The
  // set-up assistant opens again from here (only the owner sees the row).
  var backupDialog = document.getElementById("backup-dialog");
  var backupOpen = root.querySelector("[data-backup-open]");
  if (backupDialog && backupOpen) backupOpen.addEventListener("click", function () { backupDialog.showModal(); });
  var setupOpen = root.querySelector("[data-setup-open]");
  if (setupOpen) setupOpen.addEventListener("click", function () { location.href = "/setup?step=access"; });

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

  // After a restart of the hub: wait until it has gone down and answers again, then load the page anew.
  function back(tries) {
    setTimeout(function () {
      fetch("/health", { credentials: "same-origin", cache: "no-store" })
        .then(function (r) { if (r.ok && tries > 3) AgentHub.reload(); else back(tries + 1); }, function () { back(tries + 1); });
    }, 3000);
  }

  // The version and the update (routes/update.py, only the owner). The row asks the server what to show; while an update
  // runs it asks every few seconds (requests fail while the hub restarts: the gate answers with the maintenance page),
  // and the page loads anew once the update has ended well. A failed update shows its log to copy.
  var update = document.getElementById("sys-update");
  if (update) {
    var updText = update.querySelector("[data-update-text]");
    var updCheck = update.querySelector("[data-update-check]");
    var updStart = update.querySelector("[data-update-start]");
    var updFail = document.getElementById("sys-update-fail");
    var updDialog = document.getElementById("update-dialog");
    var updForm = updDialog.querySelector("form");
    var updError = updDialog.querySelector("[data-error]");
    var updWatching = false;
    var updShow = function (data) {
      updText.textContent = data.text;
      updStart.hidden = !data.available;
      updCheck.hidden = data.available;
      updCheck.disabled = updStart.disabled = data.running;
      updFail.hidden = !data.failed;
      updFail.querySelector("[data-update-failed]").textContent = data.failed;
      updFail.querySelector("[data-update-log]").textContent = data.log;
      updFail.querySelector("[data-update-log-box]").hidden = !data.log;
      if (data.running) updWatching = true;
      else if (updWatching) AgentHub.reload();   // the update has ended: the page of the new (or old) version
    };
    var updAsk = function (url, post) {
      return fetch(url, { method: post ? "POST" : "GET", credentials: "same-origin", cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { if (data && data.ok) updShow(data); }, function () {});
    };
    updAsk(update.dataset.url);
    AgentHub.live({ every: 5000, when: function () { return updWatching; }, run: function () { return updAsk(update.dataset.url); } });
    updCheck.addEventListener("click", function () {
      updCheck.disabled = true;
      updAsk("/update/check", true).then(function () { updCheck.disabled = false; });
    });
    updStart.addEventListener("click", function () { updDialog.showModal(); });
    updDialog.addEventListener("close", function () { updForm.reset(); AgentHub.clear(updForm); updError.hidden = true; });
    updForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!AgentHub.validate(updForm)) return;
      updError.hidden = true;
      fetch(updForm.dataset.url, { method: "POST", body: new FormData(updForm) })
        .then(function (response) {
          if (response.ok) { updDialog.close(); return updAsk(update.dataset.url); }
          return response.json().then(function (data) { updError.textContent = data.message || root.dataset.network; updError.hidden = false; });
        })
        .catch(function () { updError.textContent = root.dataset.network; updError.hidden = false; });
    });
  }

  var dialogs = { reboot: wire("reboot"), poweroff: wire("poweroff") };
  root.addEventListener("click", function (event) {
    var button = event.target.closest("[data-power]");
    if (button) dialogs[button.dataset.power].showModal();
  });
})();
