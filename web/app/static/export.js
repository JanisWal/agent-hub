// The project's code as a ZIP (rolepage._code_tile, web/app/exports.py): ask, wait while the runner packs it, then
// download. The note says how it goes; all texts come from the server.
(function () {
  var match = location.pathname.match(/\/projects\/(\d+)/);
  if (!match) return;
  var base = "/projects/" + match[1] + "/export";
  var WAIT_FOR = 190000;   // ms: the hub gives up a request after three minutes (exports.WAIT_SECONDS)

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-export]");
    if (!button) return;
    var tile = button.closest(".p-code");
    var note = tile.querySelector("[data-export-note]");
    var buttons = tile.querySelectorAll("[data-export]");
    function say(text) { note.textContent = text || ""; note.hidden = !text; }
    function done(text) { buttons.forEach(function (b) { b.disabled = false; }); say(text); }
    buttons.forEach(function (b) { b.disabled = true; });
    say(note.dataset.wait);
    var body = new FormData();
    if (button.dataset.export) body.append("task", button.dataset.export);
    var since = Date.now();
    fetch(base, { method: "POST", body: body }).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.ok) return done(note.dataset.failed);
      (function ask() {
        fetch(base + "/" + data.id).then(function (r) { return r.json(); }).then(function (s) {
          if (s.state === "ready") { done(""); location.href = base + "/" + data.id + "/download"; }
          else if (s.state === "waiting" && Date.now() - since < WAIT_FOR) setTimeout(ask, 1500);
          else done(note.dataset.failed);
        }).catch(function () { done(note.dataset.failed); });
      })();
    }).catch(function () { done(note.dataset.failed); });
  });
})();
