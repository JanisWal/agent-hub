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
  // The quiet status line at the foot (like the file tile): a new text rises in with a spring, after 3.5 s it fades.
  // The element is looked up each time: swapping the tile replaces it.
  function statusLine(id) {
    var timer = null;
    var spring = Motion.spring(0, Motion.MOVE, function (v) {
      var el = document.getElementById(id);
      if (!el) return;
      el.style.opacity = String(Math.max(0, Math.min(1, v)));
      el.style.transform = "translateY(" + ((1 - v) * 5) + "px)";
    }, 0.002);
    return function (text, keep) {
      var el = document.getElementById(id);
      clearTimeout(timer);
      if (!el) return;
      if (!text) { spring.to(0); return; }
      el.textContent = text;
      spring.set(0);
      spring.to(1);
      if (!keep) timer = setTimeout(function () { spring.to(0); }, 3500);
    };
  }
  var say = statusLine("dev-say");
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
  // A picture dropped on a device becomes its picture (Janis, 17.11.2026, on purpose without a hint): the browser
  // makes it 96 x 96 first (a JPEG of a few KB), the server checks it is one (devices.set_picture).
  function setPicture(id, file) {
    if (!file || !/^image\//.test(file.type)) return Promise.resolve(false);
    return createImageBitmap(file).then(function (bitmap) {
      var canvas = document.createElement("canvas");
      canvas.width = canvas.height = 96;
      var side = Math.min(bitmap.width, bitmap.height);
      canvas.getContext("2d").drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, 96, 96);
      var body = new FormData();
      body.append("picture", canvas.toDataURL("image/jpeg", 0.82));
      return post("/devices/" + id + "/picture", body);
    }).then(function (answer) {
      if (answer && answer.ok) { refresh(); say(data("pictureSaved")); return true; }
      say(errorText("picture"));
      return false;
    }, function () { say(errorText("picture")); return false; });
  }
  window.DeviceUI = { askPassword: askPassword, errorText: errorText, refresh: refresh, post: post, setPicture: setPicture,
                     statusLine: statusLine };

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
    r.querySelectorAll(".dev-btn").forEach(function (b) {
      var needs = { power: "poweroff", reboot: "reboot", update: "updates_check" }[b.dataset.btn];
      var can = (state.actions || []).indexOf(needs) >= 0;
      if (b.dataset.btn === "power") {   // off: the same button switches it on (Wake-on-LAN), if it can be woken
        var off = state.online === false;
        if (off) can = !!state.wake;
        b.dataset.wake = off ? "1" : "";
        b.dataset.tip = data(off ? "powerOn" : "powerOff");
        b.setAttribute("aria-label", b.dataset.tip);
        b.classList.toggle("wake", off && can);
      }
      b.disabled = busy || !can || (state.online === false && b.dataset.btn !== "power");
      b.classList.toggle("working", busy && (job.action || "").indexOf(needs.split("_")[0]) === 0);
    });
    var key = r.dataset.id + ":" + (job.finished || 0);
    if ((job.state === "done" || job.state === "failed") && job.finished && r.dataset.seen !== key) {
      r.dataset.seen = key;
      if (Date.now() / 1000 - job.finished < 60) {
        if (job.state === "failed") { flash(r, "stop"); say(errorText(job.error)); }
        else if (job.action === "updates_check") {
          var n = (job.result || {}).count || 0;
          flash(r, n ? "go" : "stop");
          say(n ? data("found").replace("{n}", n) : data("none"));
        }
      }
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

  function press(r, button) {   // no password for the buttons (Janis, 17.11.2026)
    var name = button.dataset.btn === "power" && button.dataset.wake === "1" ? "wake" : button.dataset.btn;
    var body = new FormData();
    body.append("button", name);
    button.classList.add("working");
    post("/devices/" + r.dataset.id + "/action", body).then(function (answer) {
      if (!answer.ok) { button.classList.remove("working"); flash(r, "stop"); say(errorText(answer.error)); return; }
      say(data("busy" + cap(answer.action || "")));
      setTimeout(poll, 1500);
    });
  }
  function cap(action) { return action.replace(/(^|_)([a-z])/g, function (m, s, c) { return c.toUpperCase(); }); }

  // --- a new device: the dialog, then the setup assistant, then its window
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
      refresh().then(function () {
        if (window.DeviceSetup) window.DeviceSetup.open(answer.id, function (id) { if (window.DeviceWindow) window.DeviceWindow.open(id); });
      });
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
  tile.addEventListener("dragover", function (event) {
    var r = event.target.closest(".device-row");
    if (!r || !event.dataTransfer || Array.prototype.indexOf.call(event.dataTransfer.types, "Files") < 0) return;
    event.preventDefault();
    tile.querySelectorAll(".device-row.hot").forEach(function (x) { if (x !== r) x.classList.remove("hot"); });
    r.classList.add("hot");
  });
  tile.addEventListener("dragleave", function (event) {
    var r = event.target.closest(".device-row");
    if (r && !r.contains(event.relatedTarget)) r.classList.remove("hot");
  });
  tile.addEventListener("drop", function (event) {
    var r = event.target.closest(".device-row");
    if (!r || !event.dataTransfer.files.length) return;
    event.preventDefault();
    r.classList.remove("hot");
    setPicture(r.dataset.id, event.dataTransfer.files[0]);
  });
  // What the manager asks to do on a device, in "waiting for you" (devices.request_action): yes or no, right there.
  document.addEventListener("click", function (event) {
    var b = event.target.closest(".dev-ask [data-answer]");
    if (!b) return;
    var item = b.closest(".dev-ask");
    var body = new FormData();
    body.append("answer", b.dataset.answer);
    item.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
    post("/devices/requests/" + item.dataset.request, body).then(function (answer) {
      if (!answer.ok) say(errorText(answer.error));
      AgentHub.swap(["waiting", "devices"]).then(poll, function () {});
    });
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  if (reduce.matches) tile.classList.add("no-motion");
  poll();
})();
