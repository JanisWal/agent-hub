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
    var runs = document.getElementById("role-" + view + "-runs");
    if (runs && !runs.querySelector("details[open]")) ids.push("role-" + view + "-runs");
    return ids;
  }

  function live(view) {
    if (view === "me") return true;
    var now = document.getElementById("role-" + view + "-now");
    return !!(now && now.querySelector(".r-now"));
  }

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
