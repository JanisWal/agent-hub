// The device window (Janis, 17.11.2026, second round): a sheet over the whole window like the file viewer.
// Left: the device. The three actions large with its state; the data as a quiet overview (the pencil opens the form,
// because the setup assistant usually set everything); access and connection in short; what the AI may ask for.
// Right: the segment slider of the file tile for shell, files, logs and the hub's log, and ONE "connect": the
// password once opens shell, files and logs together (routes/devices.py "grant"); the shell then connects by itself.
// Files work like an explorer: a path of folders to click, folders first, drag files in to upload (onto a folder
// row: into it), drag a row out to save it (Chrome, Edge), pencil to rename, trash after a question, small text
// files open in an editor. Messages stand in the quiet status line at the foot (a fixed place, nothing floats).
// The terminal (xterm.js, fixed version in /static) loads only when needed. No secret ever comes to this page.
(function () {
  "use strict";
  var win = document.getElementById("device-window");
  var confirmDialog = document.getElementById("device-confirm");
  if (!win || !window.DeviceUI) return;
  var UI = window.DeviceUI;
  var form = document.getElementById("dw-form");
  var current = null, panel = "shell", path = "", logSource = "journal";
  var granted = false, term = null, fit = null, socket = null, xtermLoading = null, confirmAction = null;
  var stateTimer = null;
  var icons = document.getElementById("dw-icons").dataset;

  function $(id) { return document.getElementById(id); }
  function t(name) { return win.dataset[name] || ""; }
  function err(code) { return UI.errorText(code, win); }
  function show(el, on) { if (el) el.hidden = !on; }
  function url(rest) { return "/devices/" + current.id + rest; }
  function cap(s) { return s.replace(/(^|[_-])([a-z])/g, function (m, x, c) { return c.toUpperCase(); }); }
  function getJSON(u) {
    return fetch(u, { credentials: "same-origin" }).then(function (r) {
      return r.json().catch(function () { return { ok: false }; }).then(function (d) { d.status = r.status; return d; });
    });
  }
  function when(stamp) { return stamp ? new Date(stamp * 1000).toLocaleString(document.documentElement.lang || "de") : ""; }
  var status = UI.statusLine("dw-status");   // the quiet line at the foot of the work area
  function connError(code) { var e = $("dw-conn-error"); e.textContent = code ? err(code) : ""; e.hidden = !code; }

  // --- open and fill ------------------------------------------------------------------------------------------------
  function load(id) {
    return getJSON("/devices/" + id + "/info").then(function (d) {
      if (!d.ok) return null;
      current = d.device;
      fill();
      return current;
    });
  }
  function fact(list, key, value, muted) {
    if (!value && value !== 0) return;
    var dt = document.createElement("dt"); dt.textContent = t("f" + cap(key));
    var dd = document.createElement("dd"); dd.textContent = String(value).replace(/\.$/, "");
    if (muted) dd.className = "muted-value";
    list.appendChild(dt); list.appendChild(dd);
  }
  function fill() {
    var d = current;
    $("dw-name").textContent = d.name;
    var row = document.querySelector('.device-row[data-id="' + d.id + '"] .device-tile');
    $("dw-icon").innerHTML = row ? row.innerHTML : "";
    var facts = $("dw-facts");
    facts.textContent = "";
    fact(facts, "kind", t("kind" + cap(d.kind)));
    fact(facts, "hostname", d.hostname);
    if (d.ip) fact(facts, "ip", d.ip); else if (d.ip_hint) fact(facts, "ip", d.ip_hint, true);
    fact(facts, "system", d.os_name || t("osNone"));
    fact(facts, "user", d.ssh_user ? d.ssh_user + (d.ssh_port !== 22 ? " · Port " + d.ssh_port : "") : "");
    fact(facts, "mac", d.mac);
    fact(facts, "description", d.description);
    var access = $("dw-access");
    access.textContent = "";
    fact(access, "login", d.has_key ? (d.auth === "password" ? t("passStored") : d.public_key ? t("keyStored") : t("keyOwn")) : t("keyNone"));
    fact(access, "hostkey", d.host_fp ? t("hostKnown") : t("hostNone"));
    if (d.sudo_ok !== null) fact(access, "rights", d.sudo_ok ? t("sudoOk") : t("sudoNo"));
    show($("dw-public"), !!d.public_key);
    $("dw-public-key").textContent = d.public_key || "";
    show($("dw-forget"), !!d.host_fp);
    show($("dw-setup-card"), !d.host_fp || !d.os_family);
    win.querySelectorAll('#dw-ai input[name="actions"]').forEach(function (box) { box.checked = d.ai_actions.indexOf(box.value) >= 0; });
    $("dw-ai-pass").checked = d.ai_password;
    show($("dw-ai-pass-box"), d.auth === "password");
    // the form (behind the pencil)
    ["name", "hostname", "ip", "description", "ssh_user", "ssh_port", "mac"].forEach(function (k) {
      if (form.elements[k]) form.elements[k].value = d[k] == null ? "" : d[k];
    });
    form.elements.kind.value = d.kind;
    form.elements.kind.dispatchEvent(new Event("change", { bubbles: true }));
    $("dw-ip-hint").textContent = d.ip_hint || "";
    show($("dw-ip-line"), !d.ip && !!d.ip_hint);
    connError("");
  }
  function editing(on) {
    form.hidden = !on;
    show($("dw-facts"), !on);
    $("dw-edit").setAttribute("aria-expanded", on ? "true" : "false");
    $("dw-error").hidden = true;
    if (on) form.elements.name.focus();
  }

  function open(id) {
    closeShell();
    granted = false;
    load(id).then(function (d) {
      if (!d) return;
      path = "";
      editing(false);
      if (!win.open) win.showModal();
      $("dw-name").focus();          // never the first "i": no ring on it (Janis, 17.11.2026)
      select(panel, true);
      poll();
    });
  }
  window.DeviceWindow = { open: open };
  win.addEventListener("close", function () { closeShell(); clearTimeout(stateTimer); current = null; granted = false; });

  // --- state and the three actions ----------------------------------------------------------------------------------
  function poll() {
    clearTimeout(stateTimer);
    if (!current || !win.open) return;
    getJSON(url("/state")).then(function (s) {
      if (!s.ok || !current) return;
      var job = s.job || {};
      var busy = job.state === "running";
      var led = busy && job.action !== "updates_check" ? "busy" : s.online === true ? "on" : s.online === false ? "off" : "";
      $("dw-led").className = "dev-led" + (led ? " led-" + led : "");
      var words = [t({ on: "ledOn", off: "ledOff", busy: "ledBusy" }[led] || "ledUnknown")];
      if (s.updates) words.push(t("updates").replace("{n}", s.updates));
      if (s.reboot_needed) words.push(t("rebootNeeded"));
      $("dw-state").textContent = words.join(" · ");
      win.querySelector(".dw-actions").classList.toggle("has-updates", s.updates > 0);
      win.querySelectorAll(".dw-actions .dev-btn").forEach(function (b) {
        var need = { power: "poweroff", reboot: "reboot", update: "updates_check" }[b.dataset.btn];
        var can = (s.actions || []).indexOf(need) >= 0;
        if (b.dataset.btn === "power" && s.online === false) {
          can = !!s.wake;
          b.dataset.tip = t("powerOn"); b.setAttribute("aria-label", t("powerOn")); $("dw-cap-power").textContent = t("powerOn");
        } else if (b.dataset.btn === "power") {
          b.dataset.tip = t("powerOff"); b.setAttribute("aria-label", t("powerOff")); $("dw-cap-power").textContent = t("powerOff");
        }
        b.disabled = busy || !can || (s.online === false && b.dataset.btn !== "power");
        b.classList.toggle("working", busy && job.action && job.action.indexOf(need.split("_")[0]) === 0);
      });
      if (job.state === "done" && job.action === "updates_check" && Date.now() / 1000 - job.finished < 15) {
        $("dw-say").textContent = (job.result || {}).count ? t("found").replace("{n}", job.result.count) : t("none");
      } else if (job.state === "failed" && Date.now() / 1000 - job.finished < 15) {
        $("dw-say").textContent = err(job.error);
      }
      stateTimer = setTimeout(poll, busy ? 3000 : 20000);
    });
  }
  win.querySelector(".dw-actions").addEventListener("click", function (event) {
    var b = event.target.closest(".dev-btn");
    if (!b || b.disabled || !current) return;
    var name = b.dataset.btn;
    if (name === "power" && b.dataset.tip === t("powerOn")) name = "wake";
    var body = new FormData();
    body.append("button", name);
    b.classList.add("working");
    UI.post(url("/action"), body).then(function (answer) {
      if (!answer.ok) { b.classList.remove("working"); $("dw-say").textContent = err(answer.error); return; }
      $("dw-say").textContent = t("busy" + cap(answer.action || "")) || "";
      setTimeout(poll, 1500);
      UI.refresh();
    });
  });

  // --- the overview and its form --------------------------------------------------------------------------------------
  $("dw-edit").addEventListener("click", function () { editing(form.hidden); });
  $("dw-edit-cancel").addEventListener("click", function () { fill(); editing(false); });
  $("dw-ip-take").addEventListener("click", function () { form.elements.ip.value = current.ip_hint; show($("dw-ip-line"), false); });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!AgentHub.validate(form)) return;
    var body = new FormData(form);
    var login = new FormData();
    ["ssh_user", "ssh_port", "mac"].forEach(function (k) { login.append(k, body.get(k) || ""); body.delete(k); });
    UI.post(url(""), body).then(function (answer) {
      if (!answer.ok) return answer;
      return UI.post(url("/login"), login);
    }).then(function (answer) {
      if (!answer.ok) {
        var e = $("dw-error");
        var key = "err" + cap(answer.error || "other");
        e.textContent = win.dataset[key] || win.dataset.errOther;
        e.hidden = false;
        return;
      }
      UI.refresh();
      load(current.id).then(function () { editing(false); status(t("saved")); });
    });
  });

  // --- access, connection, AI, delete -----------------------------------------------------------------------------------
  function setupNow() {
    if (window.DeviceSetup) window.DeviceSetup.open(current.id, function (id) { load(id); poll(); });
  }
  $("dw-setup").addEventListener("click", setupNow);
  $("dw-setup-again").addEventListener("click", setupNow);
  $("dw-test").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    connError("");
    UI.post(url("/test")).then(function (answer) {
      b.disabled = false;
      if (!answer.ok) { connError(answer.error); return; }
      UI.refresh();
      load(current.id).then(poll);
    });
  });
  $("dw-forget").addEventListener("click", function () {
    UI.askPassword(this.textContent, current.name, function (password) {
      var body = new FormData();
      body.append("password", password);
      return UI.post(url("/forget-host"), body);
    }).then(function (answer) { if (answer && answer.ok) { UI.refresh(); load(current.id); } });
  });
  function sendAi() {
    var body = new FormData();
    win.querySelectorAll('#dw-ai input[name="actions"]:checked').forEach(function (box) { body.append("actions", box.value); });
    body.append("ai_password", $("dw-ai-pass").checked ? "1" : "");
    UI.post(url("/ai"), body).then(function (answer) { status(answer.ok ? t("saved") : err(answer.error)); });
  }
  $("dw-ai").addEventListener("change", sendAi);
  $("dw-ai-pass").addEventListener("change", sendAi);
  win.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (!copy) return;
    navigator.clipboard.writeText($(copy.dataset.copy).textContent).then(function () {
      copy.classList.add("copied");
      status(t("copied"));
      setTimeout(function () { copy.classList.remove("copied"); }, 1600);
    });
  });
  function confirmThen(text, action) {
    confirmDialog.querySelector("h2").textContent = text;
    confirmAction = action;
    confirmDialog.showModal();
  }
  $("dw-delete").addEventListener("click", function () {
    confirmThen(confirmDialog.dataset.device, function () {
      UI.post(url("/delete")).then(function () { win.close(); UI.refresh(); });
    });
  });
  $("device-confirm-yes").addEventListener("click", function () {
    var act = confirmAction;
    confirmDialog.close();
    if (act) act();
  });
  confirmDialog.addEventListener("close", function () { confirmAction = null; });

  // --- tabs (the segment slider of the file tile) and the one "connect" -------------------------------------------------
  var tabs = Array.prototype.slice.call(win.querySelectorAll(".dw-tabs .file-tab"));
  var segment = window.Segment ? Segment.attach(win.querySelector(".dw-tabs"), {
    thumb: win.querySelector(".dw-tabs .file-thumb"),
    items: function () { return tabs; },
    current: function () { return tabs.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0]; },
    pick: function (b) { select(b.dataset.panel); }
  }) : null;
  function needsGrant(name) { return name !== "history"; }
  function select(name, instant) {
    panel = name;
    tabs.forEach(function (b) { b.setAttribute("aria-selected", b.dataset.panel === name ? "true" : "false"); });
    if (segment) segment.place(instant);
    var locked = needsGrant(name) && !granted;
    show($("dw-connect"), locked);
    win.querySelectorAll(".dw-panel").forEach(function (p) { p.hidden = locked || p.dataset.panel !== name; });
    if (locked) { $("dw-connect-form").elements.password.focus(); return; }
    if (name === "shell" && !socket) connectShell();
    if (name === "files") listFiles(path || "");
    if (name === "logs") loadLogs();
    if (name === "history") loadHistory();
    if (name === "shell" && fit) setTimeout(function () { fit.fit(); }, 30);
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { select(b.dataset.panel); }); });
  $("dw-connect-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var f = this;
    if (!AgentHub.validate(f)) return;
    var body = new FormData();
    body.append("password", f.elements.password.value);
    UI.post(url("/grant"), body).then(function (answer) {
      var e = $("dw-connect-error");
      if (!answer.ok) { e.textContent = answer.message || err(answer.error); e.hidden = false; return; }
      e.hidden = true;
      f.reset();
      granted = true;
      select(panel);
    });
  });
  function guarded(answer) {
    if (answer.status === 403 && answer.error === "grant") { granted = false; select(panel); return false; }
    if (!answer.ok) { status(err(answer.error)); return false; }
    return true;
  }

  // --- shell ------------------------------------------------------------------------------------------------------------
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
  }
  function connectShell() {
    loadXterm().then(function () {
      if (!term) {
        var style = getComputedStyle(document.documentElement);
        term = new window.Terminal({ cursorBlink: true, fontSize: 13, scrollback: 4000,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          theme: { background: style.getPropertyValue("--term-bg").trim(), foreground: style.getPropertyValue("--term-fg").trim(),
                   cursor: style.getPropertyValue("--accent").trim() } });
        fit = new window.FitAddon.FitAddon();
        term.loadAddon(fit);
        term.open($("dw-term"));
        term.onData(function (text) { if (socket && socket.readyState === 1) socket.send(JSON.stringify({ in: text })); });
        term.onResize(function (size) { if (socket && socket.readyState === 1) socket.send(JSON.stringify({ size: [size.cols, size.rows] })); });
        window.addEventListener("resize", function () { if (win.open && panel === "shell" && fit) fit.fit(); });
      }
      fit.fit();
      term.writeln("\x1b[2m" + t("webNote") + "\x1b[0m");
      var proto = location.protocol === "https:" ? "wss://" : "ws://";
      socket = new WebSocket(proto + location.host + url("/shell") + "?cols=" + term.cols + "&rows=" + term.rows);
      socket.binaryType = "arraybuffer";
      socket.onmessage = function (event) {
        if (typeof event.data === "string") {
          var m = {};
          try { m = JSON.parse(event.data); } catch (e) {}
          if (m.error) status(err(m.error), true);
          return;
        }
        term.write(new Uint8Array(event.data));
      };
      socket.onclose = function (event) {
        socket = null;
        if (event.code === 4403) { granted = false; select(panel); return; }
        if (term) term.writeln("\r\n\x1b[2m" + t("shellClosed") + "\x1b[0m");
      };
      term.focus();
    }, function () { status(err("failed")); });
  }

  // --- files: an explorer ---------------------------------------------------------------------------------------------
  function size(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(1) + " GB";
  }
  function join(dir, name) { return (dir === "/" ? "" : dir) + "/" + name; }
  function crumbs() {
    var nav = $("dw-crumbs");
    nav.textContent = "";
    var parts = path.split("/").filter(Boolean);
    var root = document.createElement("button");
    root.type = "button"; root.textContent = "/"; root.dataset.path = "/";
    nav.appendChild(root);
    var acc = "";
    parts.forEach(function (part, i) {
      acc += "/" + part;
      var b = document.createElement("button");
      b.type = "button"; b.textContent = part; b.dataset.path = acc;
      if (i === parts.length - 1) b.setAttribute("aria-current", "location");
      nav.appendChild(b);
    });
    nav.scrollLeft = nav.scrollWidth;
  }
  $("dw-crumbs").addEventListener("click", function (event) {
    var b = event.target.closest("[data-path]");
    if (b) listFiles(b.dataset.path);
  });
  function listFiles(where) {
    getJSON(url("/files") + "?path=" + encodeURIComponent(where || ".")).then(function (d) {
      if (!guarded(d)) return;
      path = d.path;
      crumbs();
      var list = $("dw-files");
      list.textContent = "";
      if (!d.entries.length) {
        var empty = document.createElement("li");
        empty.className = "dw-empty muted";
        empty.textContent = t("filesEmpty");
        list.appendChild(empty);
      }
      d.entries.forEach(function (e) {
        var li = document.createElement("li");
        li.className = "dw-file " + e.kind;
        li.dataset.name = e.name;
        li.dataset.kind = e.kind;
        li.dataset.size = e.size;
        li.draggable = e.kind === "file";
        var name = document.createElement("button");
        name.type = "button";
        name.className = "dw-file-name";
        name.innerHTML = e.kind === "dir" ? icons.folder : icons.file;
        var label = document.createElement("span");
        label.textContent = e.name;
        name.appendChild(label);
        var sz = document.createElement("span");
        sz.className = "dw-file-size";
        sz.textContent = e.kind === "dir" ? "" : size(e.size);
        var mt = document.createElement("span");
        mt.className = "dw-file-time";
        mt.textContent = e.mtime ? new Date(e.mtime * 1000).toLocaleDateString(document.documentElement.lang || "de") : "";
        var tools = document.createElement("span");
        tools.className = "dw-file-tools";
        [["rename", icons.pencil, t("filesRename")], ["delete", icons.trash, ""]].forEach(function (spec) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "icon-button card-btn" + (spec[0] === "delete" ? " no" : "");
          b.dataset.op = spec[0];
          b.innerHTML = spec[1];
          if (spec[2]) { b.setAttribute("aria-label", spec[2]); b.dataset.tip = spec[2]; }
          tools.appendChild(b);
        });
        li.appendChild(name); li.appendChild(sz); li.appendChild(mt); li.appendChild(tools);
        list.appendChild(li);
      });
    });
  }
  function fileOp(op, values) {
    var body = new FormData();
    Object.keys(values).forEach(function (k) { body.append(k, values[k]); });
    return UI.post(url("/files/" + op), body).then(function (answer) { return guarded(answer) ? answer : null; });
  }
  function inlineName(li, placeholder, done) {
    var host = li;
    if (!host) { host = document.createElement("li"); host.className = "dw-file"; $("dw-files").insertBefore(host, $("dw-files").firstChild); }
    var old = host.dataset.name || "";
    host.textContent = "";
    var input = document.createElement("input");
    input.className = "dw-inline";
    input.placeholder = placeholder;
    input.value = old;
    host.appendChild(input);
    input.focus();
    input.select();
    var finished = false;
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { finished = true; listFiles(path); }
      if (event.key === "Enter" && input.value.trim()) { event.preventDefault(); finished = true; done(input.value.trim()); }
    });
    input.addEventListener("blur", function () { if (!finished) listFiles(path); });
  }
  $("dw-files").addEventListener("click", function (event) {
    var li = event.target.closest(".dw-file");
    if (!li || !li.dataset.name) return;
    var full = join(path, li.dataset.name);
    var op = event.target.closest("[data-op]");
    if (op && op.dataset.op === "rename") {
      inlineName(li, t("filesRename"), function (name) { fileOp("rename", { path: full, to: join(path, name) }).then(function () { listFiles(path); }); });
      return;
    }
    if (op && op.dataset.op === "delete") {
      confirmThen(confirmDialog.dataset.file, function () { fileOp("delete", { path: full }).then(function () { listFiles(path); }); });
      return;
    }
    if (!event.target.closest(".dw-file-name")) return;
    if (li.dataset.kind !== "file") { listFiles(full); return; }
    if (Number(li.dataset.size) <= 512 * 1024) { openEditor(full); return; }
    location.href = url("/files/get") + "?path=" + encodeURIComponent(full);
  });
  // drag a file out to the desktop (Chrome and Edge understand "DownloadURL", like the file tile)
  $("dw-files").addEventListener("dragstart", function (event) {
    var li = event.target.closest(".dw-file.file");
    if (!li) return;
    var full = join(path, li.dataset.name);
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData("DownloadURL", "application/octet-stream:" + li.dataset.name + ":" + location.origin +
      url("/files/get") + "?path=" + encodeURIComponent(full));
  });
  // drag files in: onto the list = into this folder, onto a folder row = into that folder
  var dropZone = $("dw-files");
  function dropTarget(event) {
    var li = event.target.closest(".dw-file.dir");
    return li ? join(path, li.dataset.name) : path;
  }
  dropZone.addEventListener("dragover", function (event) {
    if (!event.dataTransfer || Array.prototype.indexOf.call(event.dataTransfer.types, "Files") < 0) return;
    event.preventDefault();
    dropZone.classList.add("dropping");
    dropZone.querySelectorAll(".hot").forEach(function (x) { x.classList.remove("hot"); });
    var li = event.target.closest(".dw-file.dir");
    if (li) li.classList.add("hot");
    status(t("filesDrop").replace("{path}", dropTarget(event)), true);
  });
  dropZone.addEventListener("dragleave", function (event) {
    if (event.target === dropZone) { dropZone.classList.remove("dropping"); status(""); }
  });
  dropZone.addEventListener("drop", function (event) {
    if (!event.dataTransfer || !event.dataTransfer.files.length) return;
    event.preventDefault();
    dropZone.classList.remove("dropping");
    upload(Array.prototype.slice.call(event.dataTransfer.files), dropTarget(event));
  });
  $("dw-upload").addEventListener("change", function () {
    var input = this;
    upload(Array.prototype.slice.call(input.files), path).then(function () { input.value = ""; });
  });
  function upload(list, into) {
    if (!list.length) return Promise.resolve();
    AgentHub.hold(true);
    var done = 0;
    return list.reduce(function (chain, file) {
      return chain.then(function () {
        status(t("filesUp").replace("{name}", file.name), true);
        var body = new FormData();
        body.append("path", into);
        body.append("file", file);
        return UI.post(url("/upload"), body).then(function (answer) { if (guarded(answer)) done += 1; });
      });
    }, Promise.resolve()).then(function () {
      AgentHub.hold(false);
      status(t("filesDone").replace("{n}", done));
      listFiles(path);
    });
  }
  $("dw-up").addEventListener("click", function () { listFiles(path.replace(/\/[^/]+\/?$/, "") || "/"); });
  $("dw-mkdir").addEventListener("click", function () {
    inlineName(null, t("filesFolder"), function (name) { fileOp("mkdir", { path: join(path, name) }).then(function () { listFiles(path); }); });
  });
  function openEditor(full) {
    fileOp("read", { path: full }).then(function (answer) {
      if (!answer) return;
      if (/\u0000/.test(answer.text)) { location.href = url("/files/get") + "?path=" + encodeURIComponent(full); return; }
      $("dw-editor-path").textContent = full;
      $("dw-editor-text").value = answer.text;
      show($("dw-editor"), true);
      show($("dw-files"), false);
    });
  }
  $("dw-editor-close").addEventListener("click", function () { show($("dw-editor"), false); show($("dw-files"), true); });
  $("dw-editor-save").addEventListener("click", function () {
    fileOp("write", { path: $("dw-editor-path").textContent, text: $("dw-editor-text").value }).then(function (answer) {
      if (!answer) return;
      show($("dw-editor"), false); show($("dw-files"), true);
      status(t("saved"));
      listFiles(path);
    });
  });

  // --- logs and the hub's log -------------------------------------------------------------------------------------------
  var sources = Array.prototype.slice.call(win.querySelectorAll(".dw-sources .file-tab"));
  var sourceSeg = window.Segment ? Segment.attach(win.querySelector(".dw-sources"), {
    thumb: win.querySelector(".dw-sources .file-thumb"),
    items: function () { return sources; },
    current: function () { return sources.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0]; },
    pick: function (b) { pickSource(b.dataset.source); }
  }) : null;
  function pickSource(name) {
    logSource = name;
    sources.forEach(function (b) { b.setAttribute("aria-selected", b.dataset.source === name ? "true" : "false"); });
    if (sourceSeg) sourceSeg.place();
    loadLogs();
  }
  sources.forEach(function (b) { b.addEventListener("click", function () { pickSource(b.dataset.source); }); });
  function loadLogs() {
    if (sourceSeg) sourceSeg.place(true);
    getJSON(url("/logs") + "?source=" + logSource).then(function (d) {
      if (!guarded(d)) return;
      var pre = $("dw-log");
      pre.textContent = d.text;
      pre.scrollTop = pre.scrollHeight;
    });
  }
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
        var strong = document.createElement("strong");
        strong.textContent = win.dataset["h" + cap(e.action)] || e.action;
        var small = document.createElement("small");
        small.textContent = [when(e.created_at), e.result, e.seconds ? e.seconds + " s" : "", e.origin === "ai" ? t("originAi") : "", e.detail]
          .filter(Boolean).join(" · ");
        li.appendChild(strong);
        li.appendChild(small);
        list.appendChild(li);
      });
    });
  }

  // --- a picture dropped on the device's picture in the window ----------------------------------------------------------
  $("dw-icon").addEventListener("dragover", function (event) { if (event.dataTransfer.types.indexOf("Files") >= 0) event.preventDefault(); });
  $("dw-icon").addEventListener("drop", function (event) {
    event.preventDefault();
    var file = event.dataTransfer.files[0];
    if (file && UI.setPicture) UI.setPicture(current.id, file).then(function () { load(current.id); status(t("pictureSaved")); });
  });
})();
