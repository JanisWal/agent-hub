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

  // "Send the invitation link again": no dialog (nothing is lost, the new link replaces the old one); the answer
  // appears under the role in the same row, the page is not reloaded.
  function resendInvite(button) {
    var row = button.closest(".user-row");
    var note = row.querySelector("[data-note]");
    function say(text, failed) {
      note.textContent = text || networkText;
      note.classList.toggle("is-error", failed);
      note.hidden = false;
    }
    button.disabled = true;
    fetch("/users/" + row.dataset.id + "/invite", { method: "POST" })
      .then(function (response) {
        return response.json().then(function (data) { say(data.message, !data.ok); }, function () { say("", true); });
      })
      .catch(function () { say("", true); })
      .then(function () { button.disabled = false; });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) return;
    if (button.id === "add-user") dialogOf("add-dialog").showModal();
    else if (button.hasAttribute("data-reset")) openFor(button, "reset-dialog");
    else if (button.hasAttribute("data-invite")) resendInvite(button);
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
