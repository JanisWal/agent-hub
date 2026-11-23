/* The role views of the project page (rolepage.py): while one is open and its role has a run going or waiting, its
   changing parts are swapped every few seconds (AgentHub.swap: no reload, the settings in the head stay as they are).
   "For you" is refreshed the same way while it is open (no dialog of it open: todos.js swaps after its own changes). A run list with an opened report is left alone, so the report
   does not close under the reader. Nothing is fetched while the page is hidden. */
(function () {
  "use strict";
  var EVERY = 8000, IDLE = 30000;

  function parts(view) {
    if (view === "me") return ["me-list", "me-count", "me-badge"];
    var ids = ["role-" + view + "-now", "role-" + view + "-usage", "role-" + view + "-count"];
    if (view === "programmer") ids.push("role-programmer-task", "role-programmer-trail");
    var runs = document.getElementById("role-" + view + "-runs");
    if (runs && !runs.querySelector("details[open]")) ids.push("role-" + view + "-runs");
    return ids;
  }

  function live(view) {
    if (view === "me") return true;
    var now = document.getElementById("role-" + view + "-now");
    return !!(now && now.querySelector(".r-now:not(.idle)"));
  }

  // Cancel the task on its way (rolepage._cancel): its item goes into the trash; the view and the board swap.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-cancel-task]");
    if (!button) return;
    button.disabled = true;
    fetch("/tasks/" + button.dataset.cancelTask + "/cancel", { method: "POST", credentials: "same-origin" })
      .then(function () { return AgentHub.swap(parts(document.body.dataset.openView || "programmer").concat(["board", "board-state"])); })
      .catch(function () { AgentHub.reload(); });
  });

  // What the reviewer looks at (rolepage._focus_tile): saved a moment after typing stops, and when the field is left.
  var focusField = document.getElementById("review-focus"), focusTimer = null;
  function saveFocus(said) {   // said: the line to show once it is saved (default "Saved")
    if (focusTimer) { clearTimeout(focusTimer); focusTimer = null; }
    var project = document.querySelector(".project");
    if (!focusField || !project) return;
    var body = new FormData();
    body.append("text", focusField.value);
    var state = document.getElementById("review-focus-state");
    fetch("/projects/" + project.dataset.id + "/review-focus", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { if (r.ok && state) { state.textContent = typeof said === "string" ? said : state.dataset.saved; } })
      .catch(function () {});
  }
  if (focusField) {
    focusField.addEventListener("input", function () {
      if (focusTimer) clearTimeout(focusTimer);
      focusTimer = setTimeout(saveFocus, 800);
    });
    focusField.addEventListener("change", function () { saveFocus(); });
    // A Markdown or text file dropped on the tile takes the field's place (Janis, 22.11.2026: no file field, no plus).
    var focusTile = document.getElementById("review-focus-tile");
    var focusState = document.getElementById("review-focus-state");
    var MAX_FILE = 100 * 1024;
    function isFile(event) { return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types || [], "Files") >= 0; }
    focusTile.addEventListener("dragover", function (event) {
      if (!isFile(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      focusTile.classList.add("dropping");
    });
    focusTile.addEventListener("dragleave", function (event) {
      if (!focusTile.contains(event.relatedTarget)) focusTile.classList.remove("dropping");
    });
    focusTile.addEventListener("drop", function (event) {
      if (!isFile(event)) return;
      event.preventDefault();
      focusTile.classList.remove("dropping");
      var file = event.dataTransfer.files[0];
      var textLike = file && (/^text\//.test(file.type) || /\.(md|markdown|txt)$/i.test(file.name));
      if (!textLike || file.size > MAX_FILE) { focusState.textContent = focusState.dataset.bad; return; }
      file.text().then(function (text) {
        focusField.value = text.slice(0, Number(focusField.maxLength) || text.length);
        saveFocus(focusState.dataset.taken);
      }).catch(function () { focusState.textContent = focusState.dataset.bad; });
    });
  }

  // The AI of a role (rolepage._ai_pills): a click chooses it; the pills and the model picker (which shows the models
  // of the role's AI) are swapped in at once, no reload.
  document.addEventListener("click", function (event) {
    var pill = event.target.closest("[data-role-ai]");
    if (!pill || pill.getAttribute("aria-pressed") === "true") return;
    pill.disabled = true;
    var body = new FormData();
    body.append("provider", pill.dataset.roleAi);
    fetch("/roles/" + pill.dataset.role + "/settings", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("ai"); return window.AgentHub.swap(["role-" + pill.dataset.role + "-ais"]); })
      .then(function (fresh) { window.AgentHub.refreshPickers(fresh); })
      .catch(function () { window.AgentHub.reload(); });
  });

  // The open role view follows the server through the page's one timer (core.js): quickly while its role has a run
  // going or waiting, now and then otherwise.
  function openView() {
    var view = document.body.dataset.openView;
    return document.querySelector('[data-view-panel="' + view + '"].role-view') ? view : null;
  }
  var watch = AgentHub.live({
    every: function () { var view = openView(); return view && live(view) ? EVERY : IDLE; },
    when: function () { return !!openView(); },
    parts: function () { return parts(openView()); },
  });
  document.addEventListener("agenthub:view", function () { if (openView()) watch.soon(); });
})();
