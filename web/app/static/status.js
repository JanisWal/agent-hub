// The Status tile in the Manager view (Janis, 22.11.2026: its numbers follow the board, not only an AI). The tile is
// asked for again on its own every REFRESH ms while it can be seen (counted from the database, no AI). The round arrow
// asks the hub for a new written status (statusnote.py, as often as the user likes). While one is on its way, also an
// automatic one, the server draws the arrow turning and disabled, and the tile is asked for every QUICK ms until it
// is there (both through AgentHub.live). No line of words for it: the tile says by itself when its status is new.
(function () {
  "use strict";
  var tile = document.getElementById("status");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var REFRESH = 20000, QUICK = 4000;

  function writing() {
    var button = document.getElementById("status-again");
    return !!(button && button.classList.contains("spinning"));
  }

  // Only the content changes: the tile stays the same element, so the splitter keeps its place (and follows the
  // edge it snapped to when the parts change height).
  function refresh() {
    return fetch("/projects/" + project.dataset.id + "/status/tile", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        var box = document.createElement("div");
        box.innerHTML = data.html;
        var fresh = box.firstElementChild;
        if (!fresh || (fresh.innerHTML === tile.innerHTML && fresh.className === tile.className)) return;
        tile.className = fresh.className;
        tile.innerHTML = fresh.innerHTML;
      })
      .catch(function () {});
  }

  // The page's one timer (core.js): every REFRESH ms while the tile can be seen, every QUICK ms while a status is
  // on its way (the arrow turns), until it is there.
  var watch = AgentHub.live({ every: function () { return writing() ? QUICK : REFRESH; },
                              when: function () { return !!tile.offsetParent; }, run: refresh });
  if (writing()) watch.soon();   // the page may open while one is on its way

  tile.addEventListener("click", function (event) {
    var button = event.target.closest("#status-again");
    if (!button || button.disabled) return;
    button.disabled = true;
    button.classList.add("spinning");
    fetch("/projects/" + project.dataset.id + "/status/again", { method: "POST", credentials: "same-origin" })
      .then(function () { return refresh(); });   // the numbers at once, and the arrow as the server sees it
  });
})();
