// System page (owner): restart or shut down the Pi. Each action has its own dialog with the owner's
// password; on success the dialog closes and a note says what happens now (texts come from the server).
(function () {
  var root = document.querySelector(".sys-wrap");
  if (!root) return;
  var note = root.querySelector(".sys-note");

  function wire(action) {
    var dialog = document.getElementById("power-" + action + "-dialog");
    var form = dialog.querySelector("form");
    var error = dialog.querySelector("[data-error]");

    function show(text) {
      error.textContent = text || root.dataset.network;
      error.hidden = false;
    }

    dialog.addEventListener("close", function () {
      form.reset();
      AgentHub.clear(form);
      error.hidden = true;
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!AgentHub.validate(form)) return;
      error.hidden = true;
      fetch(form.dataset.url, { method: "POST", body: new FormData(form) })
        .then(function (response) {
          if (response.ok) {
            dialog.close();
            note.textContent = note.dataset["done" + action.charAt(0).toUpperCase() + action.slice(1)];
            note.hidden = false;
            root.querySelectorAll("[data-power]").forEach(function (button) { button.disabled = true; });
            return;
          }
          return response.json().then(function (data) { show(data.message); }, function () { show(""); });
        })
        .catch(function () { show(""); });
    });
    return dialog;
  }

  var dialogs = { reboot: wire("reboot"), poweroff: wire("poweroff") };
  root.addEventListener("click", function (event) {
    var button = event.target.closest("[data-power]");
    if (button) dialogs[button.dataset.power].showModal();
  });
})();
