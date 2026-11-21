// The Status tile in the Manager view (Janis, 22.11.2026: its numbers follow the board, not only an AI). The tile is
// asked for again on its own every REFRESH ms while it can be seen (counted from the database, no AI) and at once
// after the round arrow, which also asks the hub for a new written status (statusnote.py): then it is asked for every
// few seconds until the new note is there (at most three minutes). No line of words for it (Janis, 22.11.2026: the
// tile says by itself when its status is new).
(function () {
  "use strict";
  var tile = document.getElementById("status");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var REFRESH = 20000, QUICK = 4000, LIMIT = 45;
  var polling = null;

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

  function watch(before) {
    var rounds = 0;
    clearInterval(polling);
    polling = setInterval(function () {
      rounds += 1;
      refresh().then(function () {
        var button = document.getElementById("status-again");
        if ((button && button.dataset.note !== before) || rounds >= LIMIT) { clearInterval(polling); polling = null; }
      });
    }, QUICK);
  }

  setInterval(function () {
    if (!polling && document.visibilityState === "visible" && tile.offsetParent) refresh();
  }, REFRESH);

  tile.addEventListener("click", function (event) {
    var button = event.target.closest("#status-again");
    if (!button) return;
    button.disabled = true;
    fetch("/projects/" + project.dataset.id + "/status/again", { method: "POST", credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        button.disabled = false;
        refresh();   // the numbers at once, whatever the AI does
        if (data.result === "queued") watch(button.dataset.note);
      }, function () { button.disabled = false; });
  });
})();
