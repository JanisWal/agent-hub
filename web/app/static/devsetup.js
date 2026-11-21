// The setup assistant of a device (Janis, 17.11.2026): one step at a time with "back" and "next", opened after a new
// device and from the device window, never by itself. Steps: system and SSH user, switch on SSH, own user, access
// (make a key: only its public line comes back; or a password; or an own key), rights for the buttons (or the
// Windows module for updates), password sign-in off (optional), trust the host key, test. Commands come from the
// server (routes/devices.py /setup, device_profiles.py) with the device's values put in; each has a copy button.
// Texts from data-* of the dialog (i18n.py). Needs core.js and devices.js (DeviceUI).
(function () {
  "use strict";
  var wiz = document.getElementById("device-wizard");
  if (!wiz || !window.DeviceUI) return;
  var UI = window.DeviceUI;
  var steps = Array.prototype.slice.call(wiz.querySelectorAll(".wiz-step"));
  var device = null, guide = {}, index = 0, pendingFp = "", onDone = null;
  function $(id) { return document.getElementById(id); }
  function t(name) { return wiz.dataset[name] || ""; }
  function url(rest) { return "/devices/" + device.id + rest; }
  function fail(code) { var e = $("wiz-error"); e.textContent = code ? UI.errorText(code, wiz) : ""; e.hidden = !code; }
  function state(id, text) { $(id).textContent = text || ""; }

  function visible() {   // the guide steps without a command or text for this system are left out
    return steps.filter(function (s) {
      if (s.dataset.step !== "guide") return true;
      var g = guide[s.dataset.guide];
      return !!g && !!(g.command || g.text);
    });
  }
  function fillGuide() {
    steps.forEach(function (s) {
      if (s.dataset.step !== "guide") return;
      var g = guide[s.dataset.guide];
      s.textContent = "";
      if (!g) return;
      var h = document.createElement("h3"); h.textContent = g.title; s.appendChild(h);
      var p = document.createElement("p"); p.className = "wiz-text"; p.textContent = g.text; s.appendChild(p);
      if (g.command) s.appendChild(commandBox(g.command));
    });
    var key = guide.key;
    var box = $("wiz-key-cmd");
    box.textContent = "";
    if (key && key.command) box.appendChild(commandBox(key.command));
  }
  function commandBox(command) {
    var wrap = document.createElement("div");
    wrap.className = "setup-cmd copy-box";
    var code = document.createElement("code");
    code.textContent = command;
    code.dataset.copyText = "";
    wrap.appendChild(code);
    wrap.appendChild(window.AgentHub.copyButton());   // core.js copies on a click
    return wrap;
  }

  function loadGuide(family) {
    return fetch(url("/setup") + "?family=" + encodeURIComponent(family), { credentials: "same-origin" })
      .then(function (r) { return r.json(); }).then(function (d) {
        guide = {};
        (d.steps || []).forEach(function (s) { guide[s.step] = s; });
        fillGuide();
      });
  }
  function loadDevice() {
    return fetch(url("/info"), { credentials: "same-origin" }).then(function (r) { return r.json(); })
      .then(function (d) { if (d.ok) device = d.device; return device; });
  }

  function show(i) {
    var list = visible();
    index = Math.max(0, Math.min(i, list.length - 1));
    steps.forEach(function (s) { s.hidden = s !== list[index]; });
    var dots = $("wiz-dots");
    dots.textContent = "";
    list.forEach(function (s, n) {
      var dot = document.createElement("li");
      if (n < index) dot.className = "done";
      if (n === index) dot.className = "now";
      dots.appendChild(dot);
    });
    $("wiz-count").textContent = t("step").replace("{n}", index + 1).replace("{total}", list.length);
    $("wiz-back").hidden = index === 0;
    var last = index === list.length - 1;
    var next = $("wiz-next");
    next.textContent = last ? t("finish") : t("next");
    next.classList.toggle("primary", last || !list[index].querySelector(".primary"));   // one main button per step
    fail("");
    keyState();
  }
  function keyState() {
    if (!device) return;
    state("wiz-key-state", device.has_key ? t("keyStored") : "");
    state("wiz-pass-state", device.has_password ? t("passStored") : "");
  }

  function open(id, done) {
    onDone = done || null;
    device = { id: id };
    loadDevice().then(function (d) {
      if (!d) return;
      var family = d.os_family || { mac: "macos", windows_pc: "windows", windows_server: "windows" }[d.kind] || "debian";
      var select = $("wiz-family");
      select.value = family;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      $("wiz-user").value = d.ssh_user || "";
      $("wiz-port").value = d.ssh_port || 22;
      state("wiz-host-state", d.host_fp ? t("hostTrusted") : "");
      $("wiz-fp").hidden = !d.host_fp;
      $("wiz-fp").textContent = d.host_fp || "";
      $("wiz-trust").hidden = true;
      state("wiz-test-state", "");
      return loadGuide(family).then(function () {
        if (!wiz.open) wiz.showModal();
        show(0);
        $("wiz-title").focus();
      });
    });
  }
  window.DeviceSetup = { open: open };

  $("wiz-family").addEventListener("change", function () { if (device && wiz.open) loadGuide(this.value).then(function () { show(index); }); });

  function saveLogin() {
    var body = new FormData();
    body.append("ssh_user", $("wiz-user").value.trim());
    body.append("ssh_port", $("wiz-port").value.trim() || "22");
    return UI.post(url("/login"), body).then(function (answer) {
      if (!answer.ok) { fail(answer.error === "user" || answer.error === "port" ? answer.error : "failed"); return false; }
      return loadDevice().then(function () { return loadGuide($("wiz-family").value); }).then(function () { return true; });
    });
  }
  $("wiz-next").addEventListener("click", function () {
    var list = visible();
    var current = list[index];
    var go = current.dataset.step === "system" ? saveLogin() : Promise.resolve(true);
    go.then(function (ok) {
      if (!ok) return;
      if (index === visible().length - 1) {
        wiz.close();
        UI.refresh();
        if (onDone) onDone(device.id);
        return;
      }
      show(index + 1);
    });
  });
  $("wiz-back").addEventListener("click", function () { show(index - 1); });

  // --- access
  $("wiz-keygen").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    UI.post(url("/keygen")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { fail(answer.error); return; }
      loadDevice().then(function () { return loadGuide($("wiz-family").value); }).then(keyState);
    });
  });
  function saveSecret(kind, value, field) {
    if (!value) return;
    UI.sealSecret(device.id, kind, value).then(function (answer) {
      if (!answer.ok) { fail(answer.error === "bad" ? "secret" : answer.error); return; }
      field.value = "";
      loadDevice().then(keyState);
    });
  }
  $("wiz-pass-save").addEventListener("click", function () { saveSecret("password", $("wiz-pass").value, $("wiz-pass")); });
  $("wiz-key-save").addEventListener("click", function () { saveSecret("key", $("wiz-key").value, $("wiz-key")); });

  // --- host key and test
  $("wiz-hostkey").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    fail("");
    UI.post(url("/hostkey")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { fail(answer.error); return; }
      pendingFp = answer.fingerprint;
      $("wiz-fp").hidden = false;
      $("wiz-fp").textContent = answer.fingerprint + "  ·  " + answer.address;
      if (answer.same) { state("wiz-host-state", t("hostSame")); $("wiz-trust").hidden = true; return; }
      state("wiz-host-state", answer.known ? t("hostChanged") : t("hostNew"));
      $("wiz-trust").hidden = false;
    });
  });
  $("wiz-trust").addEventListener("click", function () {
    var body = new FormData();
    body.append("fingerprint", pendingFp);
    UI.post(url("/trust"), body).then(function (answer) {
      if (!answer.ok) { fail(answer.error); return; }
      $("wiz-trust").hidden = true;
      state("wiz-host-state", t("hostTrusted"));
      show(index + 1);
    });
  });
  $("wiz-test").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    fail("");
    UI.post(url("/test")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { fail(answer.error); return; }
      state("wiz-test-state", (answer.name || "") + (answer.sudo === true ? " · " + t("sudoOk") : answer.sudo === false ? " · " + t("sudoNo") : ""));
    });
  });
})();
