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

  // The Admin and Superadmin switches (Janis, 16.11.2026): both stay on every row. The new role is shown at once, the
  // row glides to its place in the order (Motion.flip, owner > superadmin > admin > user), the server follows, then the
  // Admin: user <-> admin, a superadmin goes down to user; Superadmin: superadmin <-> admin.
  var RANK = { owner: 4, superadmin: 3, admin: 2, user: 1 };
  function switchRole(button) {
    var row = button.closest(".user-row");
    var role = row.dataset.role;
    var isSuper = button.hasAttribute("data-superadmin");
    var next = isSuper ? (role === "superadmin" ? "admin" : "superadmin") : (role === "user" ? "admin" : "user");
    var body = new FormData();
    body.append("value", isSuper ? (next === "superadmin" ? "1" : "0") : (next === "admin" ? "1" : "0"));
    var rows = Array.prototype.slice.call(row.parentNode.querySelectorAll(".user-row"));
    var order = function () {
      rows.slice().sort(function (a, b) {
        return (RANK[b.dataset.role] - RANK[a.dataset.role]) || (Number(a.dataset.id) - Number(b.dataset.id));
      }).forEach(function (el) { row.parentNode.appendChild(el); });
    };
    var move = function () {
      row.dataset.role = next;
      row.dataset.rank = RANK[next];
      row.querySelector("[data-role-label]").textContent = root.dataset["label" + next.charAt(0).toUpperCase() + next.slice(1)];
      var admin = row.querySelector("[data-admin]"), sup = row.querySelector("[data-superadmin]");
      if (admin) admin.setAttribute("aria-checked", String(next === "admin" || next === "superadmin"));
      if (sup) {   // only an admin can become a superadmin: for a normal user the switch keeps its place but is hidden
        sup.setAttribute("aria-checked", String(next === "superadmin"));
        sup.classList.toggle("is-off", next === "user");
        if (next === "user") { sup.setAttribute("tabindex", "-1"); sup.setAttribute("aria-hidden", "true"); }
        else { sup.removeAttribute("tabindex"); sup.removeAttribute("aria-hidden"); }
      }
      order();
    };
    var sent = fetch("/users/" + row.dataset.id + (isSuper ? "/superadmin" : "/admin"), { method: "POST", body: body });
    if (window.Motion && !window.Motion.reduced()) window.Motion.flip(rows, move, row); else move();
    // The screen already shows the new state, so nothing reloads when the server agrees (a reload would cut the glide
    // and flicker); only a refusal brings the real state back.
    sent.then(function (response) { if (!response.ok) AgentHub.reload(); }, function () { AgentHub.reload(); });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) return;
    if (button.id === "add-user") dialogOf("add-dialog").showModal();
    else if (button.hasAttribute("data-reset")) openFor(button, "reset-dialog");
    else if (button.hasAttribute("data-invite")) resendInvite(button);
    else if (button.hasAttribute("data-owner")) openFor(button, "owner-dialog");
    else if (button.hasAttribute("data-delete")) openFor(button, "delete-user-dialog");
    else if (button.hasAttribute("data-admin") || button.hasAttribute("data-superadmin")) switchRole(button);
  });
})();
