// The set-up assistant (setuppage.py): buttons that lead to the next step, the forms of "reachable" and "mail" (sent
// with fetch; the hub restarts with the new settings, the page waits for it and then checks the result), opening the
// drawer to connect an AI, and finishing. Texts come from the server.
(function () {
  "use strict";
  var card = document.querySelector("[data-setup]");
  if (!card) return;

  document.addEventListener("click", function (event) {
    var go = event.target.closest("[data-go]");
    if (go && !go.disabled) { location.href = go.getAttribute("data-go"); return; }
    if (event.target.closest("[data-open-drawer]")) {
      var toggle = document.getElementById("settings-toggle");
      if (toggle && toggle.getAttribute("aria-expanded") !== "true") toggle.click();
      return;
    }
    var finish = event.target.closest("[data-setup-finish]");
    if (finish) {
      finish.disabled = true;
      fetch(finish.dataset.url, { method: "POST", credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(); location.href = "/"; })
        .catch(function () { finish.disabled = false; });
    }
  });

  function dots() {
    var span = document.createElement("span");
    span.className = "loading-dots";
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = "<i></i><i></i><i></i>";
    return span;
  }
  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  // After saving, the hub writes .env and restarts. Ask for the job until it says how it went (requests fail while the
  // hub is down), then until /health answers again.
  function settled(job) {
    var tries = 0;
    function ask() {
      tries += 1;
      return fetch("/setup/job/" + job, { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.state === "ok" || data.state === "failed") return data.state;
          if (tries > 200) return "failed";
          return wait(2000).then(ask);
        }, function () { return tries > 200 ? "failed" : wait(2000).then(ask); });
    }
    function healthy() {
      return fetch("/health", { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw new Error(); },
        function () { return wait(2000).then(healthy); });
    }
    return wait(3000).then(ask).then(function (state) { return wait(4000).then(healthy).then(function () { return state; }); });
  }

  // "Reachable": three ways (home network, tunnel, own address). The chosen one shows its guide and fields, and the
  // address field takes its example and format.
  document.querySelectorAll('[data-setup-form="access"]').forEach(function (form) {
    var address = form.querySelector("[data-address]");
    var hint = address && address.parentNode.querySelector("[data-hint]");
    var here = form.querySelector('input[name="here"]');
    function choose(first) {
      var picked = form.querySelector('input[name="way"]:checked');
      if (!picked) return;
      form.querySelectorAll("[data-way]").forEach(function (part) { part.hidden = part.getAttribute("data-way") !== picked.value; });
      address.placeholder = picked.dataset.placeholder || "";
      if (hint) hint.textContent = picked.dataset.hintText || "";
      if (!first && picked.value === "home" && here && here.value && !/^http:/.test(address.value)) address.value = here.value;
      if (!first && picked.value !== "home" && /^http:/.test(address.value)) address.value = "";
    }
    form.addEventListener("change", function (event) { if (event.target.name === "way") choose(false); });
    choose(true);
  });

  document.querySelectorAll("[data-setup-form]").forEach(function (form) {
    var error = form.querySelector("[data-error]");
    var note = form.querySelector("[data-probe-note]");
    var after = form.querySelector("[data-after]");
    var save = form.querySelector('button[type="submit"]');
    function say(el, text, busy) {
      el.textContent = text || "";
      if (busy) el.appendChild(dots());
      el.hidden = !text;
    }
    function probe() {
      say(note, form.dataset.probing, true);
      return fetch(form.dataset.probe, { method: "POST", credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          say(note, data.text || card.dataset.failed);
          note.dataset.found = data.found ? "1" : "0";
          after.hidden = false;
        }, function () { say(note, card.dataset.failed); after.hidden = false; });
    }
    var again = form.querySelector("[data-probe-again]");
    if (again) again.addEventListener("click", probe);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      say(error, "");
      var body = new FormData(form);
      body.append("kind", form.getAttribute("data-setup-form"));
      save.disabled = true;
      fetch(form.dataset.url, { method: "POST", body: body, credentials: "same-origin" })
        .then(function (r) { return r.json().then(function (data) { data.status = r.status; return data; }); })
        .then(function (data) {
          if (!data.ok) {
            save.disabled = false;
            var field = data.field && form.querySelector('[name="' + data.field + '"]');
            if (field) { field.closest("label").classList.add("has-error"); field.focus(); }
            say(error, card.dataset.failed);
            return;
          }
          form.querySelectorAll('input[type="password"]').forEach(function (input) { input.value = ""; });
          say(note, form.dataset.restarting, true);
          return settled(data.job).then(function (state) {
            save.disabled = false;
            if (state !== "ok") { say(note, ""); say(error, card.dataset.failed); return; }
            // The address is checked by itself; a test mail only when the owner asks for it.
            if (form.getAttribute("data-setup-form") === "access") return probe();
            say(note, "");
            after.hidden = false;
          });
        })
        .catch(function () { save.disabled = false; say(error, card.dataset.failed); });
    });

    form.addEventListener("input", function (event) {
      var label = event.target.closest("label.has-error");
      if (label) label.classList.remove("has-error");
    });
    if (form.dataset.configured === "1") {
      if (form.getAttribute("data-setup-form") === "access") probe();
      else after.hidden = false;
    }
  });
})();
