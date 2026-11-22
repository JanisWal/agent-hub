// The emergency switch in the drawer (ui._service_rows, Janis 22.11.2026): "Pause AIs" stops the user's agent runs at
// once and starts none (agents.set_paused); "Go on" lets them work again. The manager chat is not touched. Text and
// colour change in place, no reload.
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var button = event.target.closest("#ai-pause");
    if (!button) return;
    button.disabled = true;
    var body = new FormData();
    body.append("on", button.getAttribute("aria-pressed") === "true" ? "0" : "1");
    fetch("/ai/pause", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        button.classList.toggle("paused", data.paused);
        button.setAttribute("aria-pressed", data.paused ? "true" : "false");
        button.textContent = data.paused ? button.dataset.resume : button.dataset.pause;
      })
      .catch(function () {})
      .then(function () { button.disabled = false; });
  });
})();
