// User management page: add, reset password, hand over the ownership, delete (these three with the
// asker's password) and the admin switch.
// Every action is a fetch() that answers {"ok": ..., "message": ...}; the message is already translated.
(function () {
  var root = document.querySelector(".users-wrap");
  if (!root) return;
  var networkText = root.dataset.network;
  var targetId = null;

  function dialogOf(id) { return document.getElementById(id); }

  function wire(dialog) {
    var form = dialog.querySelector("form");
    var error = dialog.querySelector("[data-error]");

    function show(text) {
      error.textContent = text || networkText;
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
      fetch(form.dataset.url.replace("{id}", targetId), { method: "POST", body: new FormData(form) })
        .then(function (response) {
          if (response.ok) { AgentHub.reload(); return; }
          return response.json().then(function (data) { show(data.message); }, function () { show(""); });
        })
        .catch(function () { show(""); });
    });
  }

  ["add-dialog", "reset-dialog", "owner-dialog", "delete-user-dialog"].forEach(function (id) { wire(dialogOf(id)); });

  function openFor(button, dialogId) {
    var row = button.closest(".user-row");
    targetId = row.dataset.id;
    var dialog = dialogOf(dialogId);
    var email = dialog.querySelector("[data-email]");
    if (email) email.textContent = row.dataset.email;
    dialog.showModal();
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) return;
    if (button.id === "add-user") dialogOf("add-dialog").showModal();
    else if (button.hasAttribute("data-reset")) openFor(button, "reset-dialog");
    else if (button.hasAttribute("data-owner")) openFor(button, "owner-dialog");
    else if (button.hasAttribute("data-delete")) openFor(button, "delete-user-dialog");
    else if (button.hasAttribute("data-admin")) {
      var body = new FormData();
      body.append("value", button.getAttribute("aria-checked") === "true" ? "0" : "1");
      fetch("/users/" + button.closest(".user-row").dataset.id + "/admin", { method: "POST", body: body })
        .then(function () { AgentHub.reload(); });
    }
  });
})();
