// Devices in the Manager view (17.11.2026): the rows with LED and the three round glass buttons, the dialog for a new
// device and the password question before serious actions. A click on a row opens the device window (devwin.js).
// LED: green = on, red = off, white = busy (restart, shut down, updates), none while unknown. Update button: the first
// press searches; found = green for 8 s, then a lasting dot (the next press installs); nothing found = red for 8 s.
// All texts come from data-* of the tile and the dialogs (i18n.py). Needs core.js.
(function () {
  "use strict";
  var tile = document.getElementById("devices");
  var dialog = document.getElementById("device-dialog");
  var pass = document.getElementById("device-pass");
  var project = document.querySelector(".project");
  if (!tile || !dialog || !pass || !project) return;
  var projectId = project.dataset.id;
  var form = dialog.querySelector("form");
  var errorLine = document.getElementById("device-error");
  var flashes = {};
  var timer = null;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  function data(name) { return tile.dataset[name] || ""; }
  function errorText(code, holder) {
    var key = "e" + String(code || "failed").replace(/(^|_)([a-z])/g, function (m, s, c) { return c.toUpperCase(); });
    return (holder || tile).dataset[key] || tile.dataset.eFailed;
  }
  function say(text) {
    var line = document.getElementById("dev-say");
    if (line) line.textContent = text || "";
  }
  function refresh() { return AgentHub.swap(["devices"]).then(poll, function () { AgentHub.reload(); }); }
  function post(url, body) {
    return fetch(url, { method: "POST", body: body || new FormData(), credentials: "same-origin" }).then(function (r) {
      return r.json().catch(function () { return { ok: false }; }).then(function (d) { d.status = r.status; return d; });
    });
  }

  // --- the password question (deps.reauth): resolves with the answer of `send(password)` once it is not refused
  function askPassword(title, text, send) {
    var f = pass.querySelector("form"), err = document.getElementById("device-pass-error");
    document.getElementById("device-pass-title").textContent = title;
    document.getElementById("device-pass-text").textContent = text || "";
    err.hidden = true;
    f.reset();
    pass.showModal();
    f.elements.password.focus();
    return new Promise(function (resolve) {
      function submit(event) {
        event.preventDefault();
        if (!AgentHub.validate(f)) return;
        send(f.elements.password.value).then(function (answer) {
          if (answer.status === 403 && answer.message || answer.status === 429) {
            err.textContent = answer.message || "";
            err.hidden = false;
            return;
          }
          cleanup();
          pass.close();
          resolve(answer);
        });
      }
      function cleanup() { f.removeEventListener("submit", submit); pass.removeEventListener("close", closed); }
      function closed() { cleanup(); resolve(null); }
      f.addEventListener("submit", submit);
      pass.addEventListener("close", closed);
    });
  }
  window.DeviceUI = { askPassword: askPassword, errorText: errorText, refresh: refresh, post: post };

  // --- LED and buttons from the state of each device
  function row(id) { return tile.querySelector('.device-row[data-id="' + id + '"]'); }
  function setLed(r, state) {
    var led = r.querySelector(".dev-led");
    if (!led) return;
    led.className = "dev-led" + (state ? " led-" + state : "");
    var label = data({ on: "ledOn", off: "ledOff", busy: "ledBusy" }[state] || "ledUnknown");
    led.setAttribute("aria-label", label);
    led.dataset.tip = label;
  }
  function flash(r, kind) {     // the update button glows green or red for about 8 seconds
    var button = r.querySelector('[data-btn="update"]');
    if (!button) return;
    clearTimeout(flashes[r.dataset.id]);
    button.classList.remove("flash-go", "flash-stop");
    void button.offsetWidth;
    button.classList.add(kind === "go" ? "flash-go" : "flash-stop");
    flashes[r.dataset.id] = setTimeout(function () { button.classList.remove("flash-go", "flash-stop"); }, 8000);
  }
  function apply(r, state) {
    var job = state.job || {};
    var busy = job.state === "running";
    setLed(r, busy && job.action !== "updates_check" ? "busy" : state.online === true ? "on" : state.online === false ? "off" : "");
    r.classList.toggle("has-updates", state.updates > 0);
    var buttons = r.querySelectorAll(".dev-btn");
    buttons.forEach(function (b) {
      var needs = { power: "poweroff", reboot: "reboot", update: "updates_check" }[b.dataset.btn];
      b.disabled = busy || (state.actions || []).indexOf(needs) < 0 || (state.online === false && b.dataset.btn !== "power");
      b.classList.toggle("working", busy && (job.action || "").indexOf(b.dataset.btn === "update" ? "updates" : b.dataset.btn === "power" ? "poweroff" : "reboot") === 0);
    });
    var power = r.querySelector('[data-btn="power"]');
    if (power && state.online === false) { power.disabled = true; power.dataset.tip = data("powerOff"); }
    var key = r.dataset.id + ":" + (job.finished || 0);
    if (job.state === "done" && job.finished && r.dataset.seen !== key) {
      r.dataset.seen = key;
      if (Date.now() / 1000 - job.finished < 60) {
        if (job.action === "updates_check") {
          var n = (job.result || {}).count || 0;
          flash(r, n ? "go" : "stop");
          say(n ? data("found").replace("{n}", n) : data("none"));
        }
      }
    } else if (job.state === "failed" && job.finished && r.dataset.seen !== key) {
      r.dataset.seen = key;
      if (Date.now() / 1000 - job.finished < 60) { flash(r, "stop"); say(errorText(job.error)); }
    }
    return busy;
  }
  function poll() {
    clearTimeout(timer);
    var rows = tile.querySelectorAll('.device-row[data-trusted="1"]');
    if (!rows.length) return;
    var busy = false;
    Promise.all(Array.prototype.map.call(rows, function (r) {
      return fetch("/devices/" + r.dataset.id + "/state", { credentials: "same-origin" }).then(function (resp) {
        return resp.ok ? resp.json() : null;
      }).then(function (state) { if (state && state.ok && apply(r, state)) busy = true; }, function () {});
    })).then(function () { timer = setTimeout(poll, busy ? 3000 : 30000); });
  }

  function press(r, button) {
    var name = button.dataset.btn;
    var installs = name === "update" && r.classList.contains("has-updates");
    var action = { power: "poweroff", reboot: "reboot" }[name] || (installs ? "updates_install" : "updates_check");
    var label = r.querySelector(".check-title").textContent.trim();
    function send(password) {
      var body = new FormData();
      body.append("button", name);
      if (password) body.append("password", password);
      return post("/devices/" + r.dataset.id + "/action", body);
    }
    var asked = action === "updates_check" ? send("") :
      askPassword(dialogTitle(action), label, send);
    asked.then(function (answer) {
      if (!answer) return;
      if (!answer.ok) { flash(r, "stop"); say(errorText(answer.error)); return; }
      say(document.getElementById("device-window").dataset["busy" + cap(action)] || "");
      button.classList.add("working");
      setTimeout(poll, 1500);
    });
  }
  function cap(action) { return action.replace(/(^|_)([a-z])/g, function (m, s, c) { return c.toUpperCase(); }); }
  function dialogTitle(action) { return document.getElementById("device-window").dataset["a" + cap(action)] || ""; }

  // --- a new device: the dialog, then its window opens (with the setup)
  function showError(code) {
    var key = "err" + (code ? code.charAt(0).toUpperCase() + code.slice(1) : "Other");
    errorLine.textContent = dialog.dataset[key] || dialog.dataset.errOther;
    errorLine.hidden = false;
  }
  dialog.addEventListener("close", function () { form.reset(); AgentHub.clear(form); errorLine.hidden = true; });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!AgentHub.validate(form)) return;
    post("/projects/" + projectId + "/devices", new FormData(form)).then(function (answer) {
      if (!answer.ok) { showError(answer.error); return; }
      dialog.close();
      refresh().then(function () { if (window.DeviceWindow) window.DeviceWindow.open(answer.id); });
    });
  });

  tile.addEventListener("click", function (event) {
    if (event.target.closest("#device-add")) {
      form.elements.kind.value = "other";
      form.elements.kind.dispatchEvent(new Event("change", { bubbles: true }));
      dialog.showModal();
      form.elements.name.focus();
      return;
    }
    var r = event.target.closest(".device-row");
    if (!r) return;
    var button = event.target.closest(".dev-btn");
    if (button) { if (!button.disabled) press(r, button); return; }
    if (window.DeviceWindow) window.DeviceWindow.open(r.dataset.id);
  });
  tile.addEventListener("keydown", function (event) {
    var r = event.target.closest(".device-row");
    if (r && event.target === r && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      if (window.DeviceWindow) window.DeviceWindow.open(r.dataset.id);
    }
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  if (reduce.matches) tile.classList.add("no-motion");
  poll();
})();
