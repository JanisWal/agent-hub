// The account page (accountpage.py). Name and language are saved as soon as they change (the page then comes back in
// the chosen language). Deleting the account asks for the password in a dialog; afterwards the login page opens.
// All texts come from the server.
(function () {
  var root = document.querySelector(".acc-wrap");
  if (!root) return;

  var profile = root.querySelector(".acc-profile");
  profile.addEventListener("change", function () {
    if (AgentHub.validate(profile)) profile.submit();
  });

  var open = root.querySelector("[data-account-delete]");
  var dialog = document.getElementById("account-delete-dialog");
  var form = dialog.querySelector("form");
  var error = dialog.querySelector("[data-error]");
  var network = root.querySelector(".sys-wrap").dataset.network;

  function show(text) {
    error.textContent = text || network;
    error.hidden = false;
  }

  open.addEventListener("click", function () { dialog.showModal(); });
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
        if (response.ok) { window.location.href = "/login"; return; }
        return response.json().then(function (data) { show(data.message); }, function () { show(""); });
      })
      .catch(function () { show(""); });
  });
})();
