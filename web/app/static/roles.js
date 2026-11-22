/* The role views of the project page (rolepage.py): while one is open and its role has a run going or waiting, its
   changing parts are swapped every few seconds (AgentHub.swap: no reload, the settings in the head stay as they are).
   "For you" is refreshed the same way while it is open (no dialog of it open: todos.js swaps after its own changes). A run list with an opened report is left alone, so the report
   does not close under the reader. Nothing is fetched while the page is hidden. */
(function () {
  "use strict";
  var EVERY = 8000, IDLE = 30000;
  var timer = null;

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
  function saveFocus() {
    if (focusTimer) { clearTimeout(focusTimer); focusTimer = null; }
    var project = document.querySelector(".project");
    if (!focusField || !project) return;
    var body = new FormData();
    body.append("text", focusField.value);
    var state = document.getElementById("review-focus-state");
    fetch("/projects/" + project.dataset.id + "/review-focus", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { if (r.ok && state) { state.textContent = state.dataset.saved; } })
      .catch(function () {});
  }
  if (focusField) {
    focusField.addEventListener("input", function () {
      if (focusTimer) clearTimeout(focusTimer);
      focusTimer = setTimeout(saveFocus, 800);
    });
    focusField.addEventListener("change", saveFocus);
  }

  // The AI of a role (rolepage._ai_pills): a click chooses it; the page comes again quietly, because the model
  // picker shows the models of the role's AI and is built when the page loads.
  document.addEventListener("click", function (event) {
    var pill = event.target.closest("[data-role-ai]");
    if (!pill || pill.getAttribute("aria-pressed") === "true") return;
    pill.disabled = true;
    var body = new FormData();
    body.append("provider", pill.dataset.roleAi);
    fetch("/roles/" + pill.dataset.role + "/settings", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("ai"); window.AgentHub.reload(); })
      .catch(function () { pill.disabled = false; });
  });

  function tick() {
    timer = null;
    var view = document.body.dataset.openView;
    var panel = document.querySelector('[data-view-panel="' + view + '"].role-view');
    if (!panel) return;
    if (document.hidden) { timer = setTimeout(tick, EVERY); return; }
    var next = live(view) ? EVERY : IDLE;   // nothing going: look now and then whether a run started
    AgentHub.swap(parts(view)).catch(function () {}).then(function () { timer = setTimeout(tick, next); });
  }

  document.addEventListener("agenthub:view", function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(tick, EVERY);
  });
})();
