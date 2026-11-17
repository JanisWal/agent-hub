// The device window (17.11.2026): settings on the left (name, address, login, host key, connection test, setup, what
// the AI may do), on the right the work on the device: shell, files, logs and the hub's log. Shell, files and logs are
// for the human only and need the password once (15 minutes, routes/devices.py "grant"). The terminal (xterm.js, a
// fixed version in /static) is loaded only when the shell is opened. No secret ever comes to this page. Texts come from
// data-* of the window (i18n.py). Needs core.js and devices.js (DeviceUI).
(function () {
  "use strict";
  var win = document.getElementById("device-window");
  var setup = document.getElementById("device-setup");
  var confirmDialog = document.getElementById("device-confirm");
  if (!win || !setup || !window.DeviceUI) return;
  var UI = window.DeviceUI;
  var form = document.getElementById("dw-form");
  var current = null;          // the device's info (routes/devices.py _info)
  var panel = "shell";
  var path = "";
  var logSource = "journal";
  var term = null, fit = null, socket = null, xtermLoading = null;
  var pendingFp = "";
  var confirmAction = null;

  function $(id) { return document.getElementById(id); }
  function t(name) { return win.dataset[name] || ""; }
  function err(code) { return UI.errorText(code, win); }
  function show(el, on) { if (el) el.hidden = !on; }
  function said(text) { $("dw-said").textContent = text || ""; }
  function url(rest) { return "/devices/" + current.id + rest; }
  function getJSON(u) {
    return fetch(u, { credentials: "same-origin" }).then(function (r) {
      return r.json().catch(function () { return { ok: false }; }).then(function (d) { d.status = r.status; return d; });
    });
  }
  function connError(code) { var e = $("dw-conn-error"); e.textContent = code ? err(code) : ""; e.hidden = !code; }
  function workError(code) { var e = $("dw-work-error"); e.textContent = code ? err(code) : ""; e.hidden = !code; }
  function when(stamp) { return stamp ? new Date(stamp * 1000).toLocaleString(document.documentElement.lang || "de") : ""; }

  // --- open and fill ----------------------------------------------------------------------------------------------
  function load(id) {
    return getJSON("/devices/" + id + "/info").then(function (d) {
      if (!d.ok) return null;
      current = d.device;
      fill();
      return current;
    });
  }
  function fill() {
    var d = current;
    $("dw-name").textContent = d.name;
    var r = document.querySelector('.device-row[data-id="' + d.id + '"] .device-tile');
    $("dw-icon").innerHTML = r ? r.innerHTML : "";
    ["name", "hostname", "ip", "description", "ssh_user", "ssh_port"].forEach(function (k) {
      if (form.elements[k]) form.elements[k].value = d[k] == null ? "" : d[k];
    });
    form.elements.kind.value = d.kind;
    form.elements.kind.dispatchEvent(new Event("change", { bubbles: true }));
    var ipField = form.elements.ip;
    ipField.placeholder = d.ip_hint || "";
    ipField.classList.toggle("dw-hinted", !d.ip && !!d.ip_hint);
    ipField.dataset.tip = !d.ip && d.ip_hint ? $("dw-ip-hint-text").textContent : "";
    show($("dw-ip-line"), !d.ip && !!d.ip_hint);
    var auth = $("dw-auth");
    auth.value = d.auth;
    auth.dispatchEvent(new Event("change", { bubbles: true }));
    authParts();
    $("dw-key-state").textContent = d.auth === "key" && d.has_key ? t("keyStored") : t("keyNone");
    $("dw-pass-state").textContent = d.auth === "password" && d.has_key ? t("passStored") : t("passNone");
    show($("dw-public"), !!d.public_key);
    $("dw-public-key").textContent = d.public_key || "";
    show($("dw-remove-box"), d.has_key);
    $("dw-remove").checked = false;
    $("dw-host").textContent = d.host_fp ? t("hostKnown") : t("hostNone");
    show($("dw-fp"), !!d.host_fp);
    $("dw-fp-text").textContent = d.host_fp ? d.host_fp + (d.pinned_ip ? "  ·  " + d.pinned_ip : "") : "";
    show($("dw-trust"), false);
    show($("dw-forget"), !!d.host_fp);
    $("dw-os").textContent = d.os_name ? d.os_name + (d.checked_at ? " · " + t("tested").replace("{when}", when(d.checked_at)) : "") : t("osNone");
    $("dw-sudo").textContent = d.sudo_ok === true ? t("sudoOk") : d.sudo_ok === false ? t("sudoNo") : "";
    if (d.reboot_needed) $("dw-sudo").textContent += (d.sudo_ok == null ? "" : " · ") + t("rebootNeeded");
    win.querySelectorAll('#dw-ai input[name="actions"]').forEach(function (box) {
      box.checked = d.ai_actions.indexOf(box.value) >= 0;
    });
    $("dw-ai-pass").checked = d.ai_password;
    show($("dw-ai-pass-box"), d.auth === "password");
    show($("dw-lan"), !d.lan_ok);
    $("dw-error").hidden = true;
    connError("");
    workError("");
    said("");
  }
  function authParts() {
    var key = $("dw-auth").value === "key";
    show($("dw-key-part"), key);
    show($("dw-pass-part"), !key);
  }

  function open(id) {
    closeShell();
    load(id).then(function (d) {
      if (!d) return;
      path = "";
      if (!win.open) win.showModal();
      select(panel);
      if (!d.host_fp && !d.has_key) openSetup();
    });
  }
  window.DeviceWindow = { open: open };
  win.addEventListener("close", function () { closeShell(); current = null; });

  // --- settings -----------------------------------------------------------------------------------------------------
  function fields(extra) {
    var body = new FormData(form);
    body.set("auth", $("dw-auth").value);
    Object.keys(extra || {}).forEach(function (k) { body.set(k, extra[k]); });
    return body;
  }
  function save(extra) {
    if (!AgentHub.validate(form)) return Promise.resolve(false);
    return UI.post(url(""), fields(extra)).then(function (answer) {
      if (!answer.ok) {
        var e = $("dw-error");
        var key = "err" + (answer.error ? answer.error.charAt(0).toUpperCase() + answer.error.slice(1) : "Other");
        e.textContent = win.dataset[key] || win.dataset.errOther;
        e.hidden = false;
        return false;
      }
      UI.refresh();
      return load(current.id).then(function () { said(t("saved")); return true; });
    });
  }
  form.addEventListener("submit", function (event) { event.preventDefault(); save(); });
  $("dw-ip-take").addEventListener("click", function () { form.elements.ip.value = current.ip_hint; save(); });
  $("dw-auth").addEventListener("change", authParts);
  $("dw-key-save").addEventListener("click", function () {
    var key = $("dw-key").value;
    if (!key.trim()) return;
    save({ key: key, auth: "key" }).then(function (done) { if (done) $("dw-key").value = ""; });
  });
  $("dw-pass-save").addEventListener("click", function () {
    var value = $("dw-pass").value;
    if (!value) return;
    save({ key: value, auth: "password" }).then(function (done) { if (done) $("dw-pass").value = ""; });
  });
  $("dw-remove").addEventListener("change", function () { if (this.checked) save({ remove_key: "1" }); });
  $("dw-keygen").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    UI.post(url("/keygen")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { connError(answer.error); return; }
      load(current.id);
    });
  });
  win.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (!copy) return;
    var text = ($(copy.dataset.copy) || copy.closest("li, .dw-public").querySelector("code")).textContent;
    navigator.clipboard.writeText(text).then(function () { copy.dataset.tip = t("copied"); copy.classList.add("copied"); setTimeout(function () { copy.classList.remove("copied"); }, 1600); });
  });
  setup.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy-step]");
    if (!copy) return;
    navigator.clipboard.writeText(copy.closest("li").querySelector("code").textContent).then(function () {
      copy.classList.add("copied");
      setTimeout(function () { copy.classList.remove("copied"); }, 1600);
    });
  });

  // --- host key, test, forget ---------------------------------------------------------------------------------------
  $("dw-hostkey").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    connError("");
    UI.post(url("/hostkey")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { connError(answer.error); return; }
      pendingFp = answer.fingerprint;
      show($("dw-fp"), true);
      $("dw-fp-text").textContent = answer.fingerprint + "  ·  " + answer.address;
      if (answer.same) { $("dw-host").textContent = t("hostSame"); show($("dw-trust"), false); return; }
      $("dw-host").textContent = answer.known ? t("hostChanged") : t("hostNew");
      show($("dw-trust"), true);
    });
  });
  $("dw-trust").addEventListener("click", function () {
    var body = new FormData();
    body.append("fingerprint", pendingFp);
    UI.post(url("/trust"), body).then(function (answer) {
      if (!answer.ok) { connError(answer.error); return; }
      UI.refresh();
      load(current.id);
    });
  });
  $("dw-test").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    connError("");
    UI.post(url("/test")).then(function (answer) {
      button.disabled = false;
      if (!answer.ok) { connError(answer.error); return; }
      UI.refresh();
      load(current.id);
    });
  });
  $("dw-forget").addEventListener("click", function () {
    UI.askPassword(this.textContent, current.name, function (password) {
      var body = new FormData();
      body.append("password", password);
      return UI.post(url("/forget-host"), body);
    }).then(function (answer) { if (answer && answer.ok) { UI.refresh(); load(current.id); } });
  });
  win.querySelector("#dw-ai").addEventListener("change", sendAi);
  $("dw-ai-pass").addEventListener("change", sendAi);
  function sendAi() {
    var body = new FormData();
    win.querySelectorAll('#dw-ai input[name="actions"]:checked').forEach(function (box) { body.append("actions", box.value); });
    body.append("ai_password", $("dw-ai-pass").checked ? "1" : "");
    UI.post(url("/ai"), body).then(function (answer) { said(answer.ok ? t("saved") : err(answer.error)); });
  }
  $("dw-delete").addEventListener("click", function () {
    confirmDialog.querySelector("h2").textContent = confirmDialog.dataset.device || confirmDialog.querySelector("h2").textContent;
    confirmAction = function () {
      UI.post(url("/delete")).then(function () { win.close(); UI.refresh(); });
    };
    confirmDialog.showModal();
  });
  document.getElementById("device-confirm-yes").addEventListener("click", function () {
    var act = confirmAction;
    confirmDialog.close();
    if (act) act();
  });
  confirmDialog.addEventListener("close", function () { confirmAction = null; });

  // --- setup guide --------------------------------------------------------------------------------------------------
  function openSetup(family) {
    getJSON(url("/setup") + (family ? "?family=" + encodeURIComponent(family) : "")).then(function (d) {
      if (!d.ok) return;
      var select = $("setup-family");
      select.value = d.family;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      var list = $("setup-steps");
      list.textContent = "";
      d.steps.forEach(function (s) {
        var li = document.createElement("li");
        var h = document.createElement("h3");
        h.textContent = s.title;
        var p = document.createElement("p");
        p.textContent = s.text;
        li.appendChild(h);
        li.appendChild(p);
        if (s.command) {
          var box = document.createElement("div");
          box.className = "setup-cmd";
          var code = document.createElement("code");
          code.textContent = s.command;
          var copy = document.createElement("button");
          copy.type = "button";
          copy.className = "icon-button card-btn";
          copy.dataset.copyStep = "1";
          copy.setAttribute("aria-label", t("copied"));
          copy.innerHTML = $("dw-copy-icon").innerHTML;
          box.appendChild(code);
          box.appendChild(copy);
          li.appendChild(box);
        }
        list.appendChild(li);
      });
      if (!setup.open) setup.showModal();
    });
  }
  $("dw-setup").addEventListener("click", function () { openSetup(); });
  $("setup-family").addEventListener("change", function () { if (setup.open && current) openSetup(this.value); });

  // --- tabs and the grant -------------------------------------------------------------------------------------------
  function select(name) {
    panel = name;
    win.querySelectorAll(".dw-tab").forEach(function (tab) { tab.setAttribute("aria-selected", tab.dataset.panel === name ? "true" : "false"); });
    win.querySelectorAll(".dw-panel").forEach(function (p) { p.hidden = p.dataset.panel !== name; });
    show($("dw-grant"), false);
    workError("");
    if (name === "files") listFiles(path || "");
    if (name === "logs") loadLogs();
    if (name === "history") loadHistory();
  }
  win.querySelector(".dw-tabs").addEventListener("click", function (event) {
    var tab = event.target.closest(".dw-tab");
    if (tab) select(tab.dataset.panel);
  });
  var afterGrant = null;
  function needGrant(again) {
    afterGrant = again;
    show($("dw-grant"), true);
    $("dw-grant-form").elements.password.focus();
  }
  $("dw-grant-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var f = this;
    if (!AgentHub.validate(f)) return;
    var body = new FormData();
    body.append("password", f.elements.password.value);
    UI.post(url("/grant"), body).then(function (answer) {
      var e = $("dw-grant-error");
      if (!answer.ok) { e.textContent = answer.message || err(answer.error); e.hidden = false; return; }
      e.hidden = true;
      f.reset();
      show($("dw-grant"), false);
      if (afterGrant) afterGrant();
    });
  });
  function guarded(answer, again) {
    if (answer.status === 403 && answer.error === "grant") { needGrant(again); return false; }
    if (!answer.ok) { workError(answer.error); return false; }
    workError("");
    return true;
  }

  // --- shell ----------------------------------------------------------------------------------------------------------
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  function loadXterm() {
    if (window.Terminal) return Promise.resolve();
    if (!xtermLoading) {
      var css = document.createElement("link");
      css.rel = "stylesheet"; css.href = win.dataset.xtermCss;
      document.head.appendChild(css);
      xtermLoading = loadScript(win.dataset.xterm).then(function () { return loadScript(win.dataset.xtermFit); });
    }
    return xtermLoading;
  }
  function closeShell() {
    if (socket) { try { socket.close(); } catch (e) {} socket = null; }
    $("dw-shell-go").hidden = false;
  }
  function connectShell() {
    loadXterm().then(function () {
      var box = $("dw-term");
      if (!term) {
        var style = getComputedStyle(document.documentElement);
        term = new window.Terminal({ cursorBlink: true, fontSize: 13, convertEol: false, scrollback: 4000,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          theme: { background: style.getPropertyValue("--term-bg").trim() || "#1b1410",
                   foreground: style.getPropertyValue("--term-fg").trim() || "#f6e6d8" } });
        fit = new window.FitAddon.FitAddon();
        term.loadAddon(fit);
        term.open(box);
        term.onData(function (text) { if (socket && socket.readyState === 1) socket.send(JSON.stringify({ in: text })); });
        term.onResize(function (size) { if (socket && socket.readyState === 1) socket.send(JSON.stringify({ size: [size.cols, size.rows] })); });
        window.addEventListener("resize", function () { if (win.open && panel === "shell") fit.fit(); });
      }
      fit.fit();
      term.writeln("\x1b[2m" + t("webNote") + "\x1b[0m");
      var proto = location.protocol === "https:" ? "wss://" : "ws://";
      socket = new WebSocket(proto + location.host + url("/shell") + "?cols=" + term.cols + "&rows=" + term.rows);
      socket.binaryType = "arraybuffer";
      $("dw-shell-go").hidden = true;
      socket.onmessage = function (event) {
        if (typeof event.data === "string") {
          var m = {};
          try { m = JSON.parse(event.data); } catch (e) {}
          if (m.error) workError(m.error);
          return;
        }
        term.write(new Uint8Array(event.data));
      };
      socket.onclose = function (event) {
        socket = null;
        $("dw-shell-go").hidden = false;
        if (event.code === 4403) { needGrant(connectShell); return; }
        term.writeln("\r\n\x1b[2m" + t("shellClosed") + "\x1b[0m");
      };
      term.focus();
    }, function () { workError("failed"); });
  }
  $("dw-shell-go").addEventListener("click", connectShell);

  // --- files ----------------------------------------------------------------------------------------------------------
  function listFiles(where) {
    getJSON(url("/files") + "?path=" + encodeURIComponent(where || ".")).then(function (d) {
      if (!guarded(d, function () { listFiles(where); })) return;
      path = d.path;
      $("dw-path").textContent = d.path;
      var list = $("dw-files");
      list.textContent = "";
      if (!d.entries.length) {
        var empty = document.createElement("li");
        empty.className = "muted dw-empty";
        empty.textContent = t("filesEmpty");
        list.appendChild(empty);
      }
      d.entries.forEach(function (e) {
        var li = document.createElement("li");
        li.className = "dw-file " + e.kind;
        li.dataset.name = e.name;
        li.dataset.kind = e.kind;
        var name = document.createElement("button");
        name.type = "button";
        name.className = "dw-file-name";
        name.textContent = e.name + (e.kind === "dir" ? "/" : "");
        var meta = document.createElement("small");
        meta.textContent = e.kind === "dir" ? "" : size(e.size);
        li.appendChild(name);
        li.appendChild(meta);
        ["rename", "delete"].forEach(function (op) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "icon-button card-btn" + (op === "delete" ? " no" : "");
          b.dataset.op = op;
          b.setAttribute("aria-label", t(op === "delete" ? "filesDelete" : "filesRename"));
          b.dataset.tip = b.getAttribute("aria-label");
          b.innerHTML = $(op === "delete" ? "dw-trash-icon" : "dw-pencil-icon").innerHTML;
          li.appendChild(b);
        });
        list.appendChild(li);
      });
    });
  }
  function size(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }
  function join(name) { return (path === "/" ? "" : path) + "/" + name; }
  function fileOp(op, values) {
    var body = new FormData();
    Object.keys(values).forEach(function (k) { body.append(k, values[k]); });
    return UI.post(url("/files/" + op), body).then(function (answer) {
      return guarded(answer, function () { fileOp(op, values); }) ? answer : null;
    });
  }
  function inlineName(li, placeholder, done) {
    var input = document.createElement("input");
    input.className = "dw-inline";
    input.placeholder = placeholder;
    input.value = li && li.dataset.name || "";
    var host = li || document.createElement("li");
    if (!li) { host.className = "dw-file"; $("dw-files").insertBefore(host, $("dw-files").firstChild); }
    host.textContent = "";
    host.appendChild(input);
    input.focus();
    input.select();
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { listFiles(path); }
      if (event.key === "Enter" && input.value.trim()) { event.preventDefault(); done(input.value.trim()); }
    });
    input.addEventListener("blur", function () { setTimeout(function () { if (document.activeElement !== input) listFiles(path); }, 150); });
  }
  $("dw-files").addEventListener("click", function (event) {
    var li = event.target.closest(".dw-file");
    if (!li || !li.dataset.name) return;
    var op = event.target.closest("[data-op]");
    var full = join(li.dataset.name);
    if (op && op.dataset.op === "rename") {
      inlineName(li, t("filesRename"), function (name) { fileOp("rename", { path: full, to: join(name) }).then(function () { listFiles(path); }); });
      return;
    }
    if (op && op.dataset.op === "delete") {
      confirmDialog.querySelector("h2").textContent = confirmDialog.dataset.file;
      confirmAction = function () { fileOp("delete", { path: full }).then(function () { listFiles(path); }); };
      confirmDialog.showModal();
      return;
    }
    if (!event.target.closest(".dw-file-name")) return;
    if (li.dataset.kind === "dir" || li.dataset.kind === "link") { listFiles(full); return; }
    var meta = li.querySelector("small").textContent;
    if (/^\d+(\.\d)? (B|KB)$/.test(meta)) { openEditor(full); return; }
    location.href = url("/files/get") + "?path=" + encodeURIComponent(full);
  });
  $("dw-up").addEventListener("click", function () {
    listFiles(path.replace(/\/[^/]+\/?$/, "") || "/");
  });
  $("dw-mkdir").addEventListener("click", function () {
    inlineName(null, t("filesFolder"), function (name) { fileOp("mkdir", { path: join(name) }).then(function () { listFiles(path); }); });
  });
  $("dw-upload").addEventListener("change", function () {
    var file = this.files[0];
    var input = this;
    if (!file) return;
    var body = new FormData();
    body.append("path", path);
    body.append("file", file);
    AgentHub.hold(true);
    UI.post(url("/upload"), body).then(function (answer) {
      AgentHub.hold(false);
      input.value = "";
      if (guarded(answer, function () {})) listFiles(path);
    });
  });
  function openEditor(full) {
    fileOp("read", { path: full }).then(function (answer) {
      if (!answer) return;
      var text = answer.text;
      if (/\u0000/.test(text)) { location.href = url("/files/get") + "?path=" + encodeURIComponent(full); return; }
      $("dw-editor-path").textContent = full;
      $("dw-editor-text").value = text;
      show($("dw-editor"), true);
      show($("dw-files"), false);
    });
  }
  $("dw-editor-close").addEventListener("click", function () { show($("dw-editor"), false); show($("dw-files"), true); });
  $("dw-editor-save").addEventListener("click", function () {
    fileOp("write", { path: $("dw-editor-path").textContent, text: $("dw-editor-text").value }).then(function (answer) {
      if (answer) { show($("dw-editor"), false); show($("dw-files"), true); listFiles(path); }
    });
  });

  // --- logs and the hub's log ---------------------------------------------------------------------------------------
  function loadLogs() {
    var pre = $("dw-log");
    getJSON(url("/logs") + "?source=" + logSource).then(function (d) {
      if (!guarded(d, loadLogs)) return;
      pre.textContent = d.text;
      pre.scrollTop = pre.scrollHeight;
    });
  }
  win.querySelectorAll(".dw-src").forEach(function (b) {
    b.addEventListener("click", function () {
      logSource = b.dataset.source;
      win.querySelectorAll(".dw-src").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      loadLogs();
    });
  });
  $("dw-logs-again").addEventListener("click", loadLogs);
  function loadHistory() {
    getJSON(url("/history")).then(function (d) {
      var list = $("dw-history");
      list.textContent = "";
      if (!d.ok) return;
      if (!d.entries.length) {
        var empty = document.createElement("li");
        empty.className = "muted";
        empty.textContent = t("historyEmpty");
        list.appendChild(empty);
      }
      d.entries.forEach(function (e) {
        var li = document.createElement("li");
        var key = "h" + e.action.replace(/(^|_)([a-z])/g, function (m, s, c) { return c.toUpperCase(); });
        var what = win.dataset[key] || e.action;
        var strong = document.createElement("strong");
        strong.textContent = what;
        var small = document.createElement("small");
        small.textContent = [when(e.created_at), e.result, e.seconds ? e.seconds + " s" : "", e.origin === "ai" ? t("originAi") : "", e.detail]
          .filter(Boolean).join(" · ");
        li.appendChild(strong);
        li.appendChild(small);
        list.appendChild(li);
      });
    });
  }
})();
