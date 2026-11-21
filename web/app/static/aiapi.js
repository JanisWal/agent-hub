// Loaded on every logged-in page: the right half of the dialogs of Claude and ChatGPT (ui.api_panel, 21.11.2026), the
// user's API key next to the plan. Saving sends the settings and, if typed, the key (the runner checks it); the key
// leaves the page once and is not kept here. All texts come from the server.
(function () {
  document.querySelectorAll("[data-api]").forEach(function (panel) {
    var provider = panel.dataset.api;
    var form = panel.querySelector("[data-api-form]");
    var state = panel.querySelector("[data-api-state]");
    if (!form) return;

    function say(text) { if (state) state.textContent = text; }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var body = new FormData(form);
      form.querySelector("[name=key]").value = "";   // the key does not stay in the page
      fetch("/ai/" + provider + "/api", { method: "POST", body: body })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (data) {
          if (!data.ok) { say(form.dataset.failed); return; }
          say(form.dataset.saved);
          setTimeout(function () { window.AgentHub.reload(); }, 900);
        })
        .catch(function () { say(form.dataset.failed); });
    });

    var remove = panel.querySelector("[data-api-remove]");
    if (remove) remove.addEventListener("click", function () {
      remove.disabled = true;
      fetch("/ai/" + provider + "/api/remove", { method: "POST" }).then(function () { window.AgentHub.reload(); });
    });
  });
})();
