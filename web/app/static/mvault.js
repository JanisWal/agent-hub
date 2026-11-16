// Trash of the files and chat archive in the Manager view (Janis, 14.11.2026). The two round buttons next to the gear
// work like trash and archive of the board (board.js): the same button again brings the tiles back. The trash list
// comes from the server and is swapped after a change (AgentHub.swap); the archive is fetched when it is opened and
// grouped by day in the browser (its own clock and language). Texts come from data-* attributes; everything the user
// or the AI wrote goes in with textContent only. Needs core.js.
(function () {
  var vault = document.getElementById("mvault");
  var manager = document.getElementById("manager-view");
  var project = document.querySelector(".project");
  if (!vault || !manager || !project) return;
  var projectId = project.dataset.id;
  var toggles = document.querySelectorAll(".m-extra");
  var list = document.getElementById("chat-archive");
  var empty = document.getElementById("chat-archive-empty");
  var confirmDialog = document.getElementById("mvault-confirm");
  var dayDialog = document.getElementById("archive-dialog");
  var lang = document.documentElement.lang || "de";
  var current = "", pending = null, days = [];

  function setView(view) {
    current = view;
    vault.hidden = !view;
    manager.classList.toggle("vault-open", !!view);
    Array.prototype.forEach.call(vault.querySelectorAll(".vault-view"), function (part) {
      part.hidden = part.dataset.mview !== view;
    });
    Array.prototype.forEach.call(toggles, function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.mview === view));
    });
    if (view) { vault.classList.remove("appear"); void vault.offsetWidth; vault.classList.add("appear"); }
    if (view === "archive") { loadArchive(); refreshVersions(); }
  }
  Array.prototype.forEach.call(toggles, function (button) {
    button.addEventListener("click", function () { setView(current === button.dataset.mview ? "" : button.dataset.mview); });
  });
  window.AgentHub = window.AgentHub || {};
  window.AgentHub.closeManagerVault = function () { if (current) setView(""); };   // stations.js, on leaving the view

  function post(url, body) { return fetch(url, { method: "POST", body: body || null, credentials: "same-origin" }); }
  function confirmThen(key, action) {
    document.getElementById("mvault-confirm-text").textContent = confirmDialog.dataset[key];
    pending = action;
    confirmDialog.showModal();
  }
  document.getElementById("mvault-confirm-yes").addEventListener("click", function () {
    var run = pending;
    confirmDialog.close();
    if (run) run();
  });
  confirmDialog.addEventListener("close", function () { pending = null; });

  // --- trash of the files
  function refreshTrash() { return AgentHub.swap(["mvault-trash"]).catch(function () {}); }
  document.addEventListener("hub:trash-changed", refreshTrash);           // files.js put something in
  vault.addEventListener("click", function (event) {
    var button = event.target.closest("[data-ftrash]");
    if (!button) return;
    var job = button.dataset.ftrash;
    if (job === "empty") {
      confirmThen("empty", function () { post("/projects/" + projectId + "/files/trash/empty").then(refreshTrash); });
      return;
    }
    var id = button.closest(".trash-row").dataset.id;
    if (job === "restore") {
      post("/files/" + id + "/restore").then(function () {
        refreshTrash();
        document.dispatchEvent(new CustomEvent("hub:files-changed"));    // files.js shows it in its area again
      });
    } else {
      confirmThen("purge", function () { post("/files/" + id + "/purge").then(refreshTrash); });
    }
  });

  // --- chat archive: one row per day, a click shows that day like the chat
  function dayKey(date) { return date.getFullYear() + "-" + (date.getMonth() + 1) + "-" + date.getDate(); }
  function time(date) { return date.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" }); }
  function loadArchive() {
    fetch("/projects/" + projectId + "/chat/archive", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) { if (data.ok) renderArchive(data.entries); })
      .catch(function () {});
  }
  function renderArchive(entries) {
    var byDay = {};
    days = [];
    entries.forEach(function (entry) {
      var date = new Date(entry.at * 1000), key = dayKey(date);
      if (!byDay[key]) { byDay[key] = { date: date, entries: [] }; days.push(byDay[key]); }
      byDay[key].entries.push(entry);
    });
    days.reverse();                                                       // the newest day first
    list.textContent = "";
    empty.hidden = days.length > 0;
    days.forEach(function (day, index) {
      var row = document.createElement("li");
      row.className = "trash-row archive-row";
      row.dataset.day = String(index);
      var title = document.createElement("button");
      title.type = "button";
      title.className = "trash-title archive-open";
      title.textContent = day.date.toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
      var small = document.createElement("small");
      var n = day.entries.length;
      var last = new Date(day.entries[n - 1].at * 1000);
      small.textContent = (n === 1 ? list.dataset.question : list.dataset.questions.replace("{n}", n)) + " · " +
        time(day.date) + (n > 1 ? " – " + time(last) : "");
      title.appendChild(small);
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "icon-button card-btn no archive-delete";
      remove.setAttribute("aria-label", list.dataset.delete);
      remove.dataset.tip = list.dataset.delete;
      remove.appendChild(document.querySelector("#archive-dialog [data-close] svg").cloneNode(true));
      row.appendChild(title);
      row.appendChild(remove);
      list.appendChild(row);
    });
  }
  function line(kind, who, text) {
    var item = document.createElement("li");
    item.className = "chat-msg " + kind;
    var name = document.createElement("span");
    name.className = "chat-who";
    name.textContent = who;
    var body = document.createElement("span");
    body.className = "chat-text";
    body.textContent = text;
    item.appendChild(name);
    item.appendChild(body);
    return item;
  }
  function openDay(day) {
    var log = document.getElementById("archive-dialog-log");
    document.getElementById("archive-dialog-title").textContent =
      day.date.toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    log.textContent = "";
    day.entries.forEach(function (entry) {
      log.appendChild(line("you", list.dataset.you + " · " + time(new Date(entry.at * 1000)), entry.prompt));
      if (entry.failure) {
        var key = { auth: "failAuth", timeout: "failTimeout", steps: "failSteps", limit: "failLimit" }[entry.failure] || "failOther";
        log.appendChild(line("claude failed", list.dataset.claude, list.dataset.failed + ": " + list.dataset[key]));
      } else {
        log.appendChild(line("claude", list.dataset.claude + (entry.model ? " · " + entry.model : ""), entry.answer));
      }
    });
    dayDialog.showModal();
    log.scrollTop = 0;
  }
  list.addEventListener("click", function (event) {
    var row = event.target.closest(".archive-row");
    if (!row) return;
    var day = days[Number(row.dataset.day)];
    if (event.target.closest(".archive-delete")) {
      confirmThen("day", function () {
        var body = new FormData();
        body.append("ids", day.entries.map(function (e) { return e.id; }).join(","));
        post("/projects/" + projectId + "/chat/archive/delete", body).then(loadArchive);
      });
    } else if (event.target.closest(".archive-open")) {
      openDay(day);
    }
  });

  // --- earlier versions of the memory files (memory.py): the list comes from the server, a text is fetched when its
  // row is opened, the round arrow puts it back (the current text becomes a version itself, so nothing is lost)
  function refreshVersions() { return AgentHub.swap(["mvault-versions"]).catch(function () {}); }
  vault.addEventListener("toggle", function (event) {
    var details = event.target;
    var row = details.closest && details.closest(".version-row");
    if (!row || !details.open) return;
    var box = details.querySelector(".version-text");
    if (box.dataset.loaded) return;
    fetch("/memory/versions/" + row.dataset.id, { credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) { if (data && data.ok) { box.textContent = data.text; box.dataset.loaded = "1"; } })
      .catch(function () {});
  }, true);   // toggle does not bubble
  vault.addEventListener("click", function (event) {
    var button = event.target.closest('[data-mversion="restore"]');
    if (!button) return;
    event.preventDefault();   // the button sits in the summary: it must not open the row
    var row = button.closest(".version-row");
    post("/memory/versions/" + row.dataset.id + "/restore").then(function () {
      refreshVersions();
      AgentHub.swap(["files"]).catch(function () {});
    });
  });
})();
