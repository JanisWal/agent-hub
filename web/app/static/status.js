// The Status tile in the Manager view: the round arrow asks the hub for a new written status (statusnote.py). The
// answer is said in the quiet line of the tile (a fixed place, nothing floats); when a round was queued, the tile is
// swapped every few seconds until the new note is there (at most three minutes). Texts come from data-* on the button.
(function () {
  "use strict";
  var tile = document.getElementById("status");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var polling = null;

  function say(text) {
    var line = document.getElementById("status-say");
    if (line) line.textContent = text || "";
  }

  function watch(before) {
    var rounds = 0;
    clearInterval(polling);
    polling = setInterval(function () {
      rounds += 1;
      AgentHub.swap(["status"]).then(function () {
        var button = document.getElementById("status-again");
        if ((button && button.dataset.note !== before) || rounds >= 18) clearInterval(polling);
      }, function () { clearInterval(polling); });
    }, 10000);
  }

  tile.addEventListener("click", function (event) {
    var button = event.target.closest("#status-again");
    if (!button) return;
    button.disabled = true;
    fetch("/projects/" + project.dataset.id + "/status/again", { method: "POST", credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        button.disabled = false;
        say(button.dataset[data.result] || button.dataset.wait);
        if (data.result === "queued") watch(button.dataset.note);
      }, function () { button.disabled = false; });
  });
})();
