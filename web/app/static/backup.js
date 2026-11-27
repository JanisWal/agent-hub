// The backup (backuppage.py): the recovery key, the nightly hour, "back up now", downloading, and putting a backup back.
// Used in the administration's backup dialog and in the set-up assistant. Texts come from the server (data-*); every
// action is a fetch, the page never reloads. Long jobs (a backup, opening one) are asked about every few seconds.
(function () {
  "use strict";

  function post(url, fields) {
    var body = new FormData();
    Object.keys(fields || {}).forEach(function (k) { body.append(k, fields[k]); });
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(function (r) {
      return r.json().then(function (data) { data.status = r.status; return data; }, function () { return { ok: false, status: r.status }; });
    });
  }
  function getJson(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); });
  }
  function say(el, text) { if (!el) return; el.textContent = text || ""; el.hidden = !text; }
  function steps(root, name) {
    Array.prototype.forEach.call(root.children, function (child) {
      if (child.hasAttribute("data-step")) child.hidden = child.getAttribute("data-step") !== name;
    });
  }
  function dots() {
    var span = document.createElement("span");
    span.className = "loading-dots";
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = "<i></i><i></i><i></i>";
    return span;
  }

  // --- the recovery key: made on the server, shown once, copied or saved as a file
  document.querySelectorAll("[data-backup-key]").forEach(function (box) {
    var error = box.querySelector("[data-error]");
    var make = box.querySelector("[data-key-make]");
    var made = null;
    make.addEventListener("click", function () {
      var password = box.querySelector("[data-key-password]");
      var ask = box.querySelector("[data-key-ask]");
      if (ask && ask.hidden) { ask.hidden = false; password.focus(); return; }   // replacing a key: the password first
      say(error, "");
      make.disabled = true;
      post(box.dataset.url, { confirm: password ? password.value : "" }).then(function (data) {
        make.disabled = false;
        if (!data.ok) { say(error, data.message || box.dataset.failed); return; }
        made = data;
        box.querySelector("[data-key-text]").textContent = data.key.trim().split("\n").pop();
        steps(box, "show");
        lockNext(true);
      }, function () { make.disabled = false; say(error, box.dataset.failed); });
    });
    box.querySelector("[data-key-file]").addEventListener("click", function () {
      if (!made) return;
      var link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([made.key], { type: "text/plain" }));
      link.download = made.name;
      document.body.appendChild(link);
      link.click();
      setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    });
    var saved = box.querySelector("[data-key-saved]");
    saved.addEventListener("change", function () { lockNext(!saved.checked); });
    // In the set-up, "on" waits until the key is put away (the dialog of the administration has no "on").
    function lockNext(on) {
      var card = box.closest("[data-setup]");
      if (!card) return;
      card.querySelectorAll(".actions [data-go]").forEach(function (b) { b.disabled = on; });
    }
  });

  // --- the hour of the nightly backup: saved when chosen
  document.querySelectorAll("[data-backup-hour]").forEach(function (select) {
    select.addEventListener("change", function () { post(select.dataset.url, { value: select.value }); });
  });

  // --- the list and downloading (password first, then a one-time address)
  var list = document.getElementById("backup-list");
  function refreshList(html) { if (list && typeof html === "string") list.innerHTML = html; }   // escaped by the server
  if (list) {
    var section = list.parentElement;
    var ask = section.querySelector("[data-download]");
    var listError = section.querySelector("[data-download-error]");
    var wanted = "";
    list.addEventListener("click", function (event) {
      var get = event.target.closest("[data-backup-get]");
      if (!get) return;
      wanted = get.getAttribute("data-backup-get");
      say(listError, "");
      ask.hidden = false;
      ask.querySelector("[data-download-password]").focus();
    });
    ask.querySelector("[data-download-cancel]").addEventListener("click", function () { ask.hidden = true; });
    ask.querySelector("[data-download-go]").addEventListener("click", function () {
      var field = ask.querySelector("[data-download-password]");
      post(ask.dataset.url, { name: wanted, confirm: field.value }).then(function (data) {
        if (!data.ok) { say(listError, data.message || (list.closest("[data-failed]") || document.body).dataset.failed || ""); return; }
        field.value = "";
        ask.hidden = true;
        location.href = data.url;
      });
    });
  }

  // --- back up now: start, then ask how it is going until it is over
  document.querySelectorAll("[data-backup-now]").forEach(function (box) {
    var start = box.querySelector("[data-backup-start]");
    var note = box.querySelector("[data-backup-note]");
    function poll(tries) {
      getJson(box.dataset.state).then(function (data) {
        if (!data.ok) return;
        refreshList(data.list);
        if (data.job.state === "running" && tries < 2400) {
          setTimeout(function () { poll(tries + 1); }, 3000);
          return;
        }
        start.disabled = false;
        say(note, data.job.text);
      }, function () { setTimeout(function () { poll(tries + 1); }, 5000); });
    }
    function running() {
      start.disabled = true;
      say(note, box.dataset.running);
      note.appendChild(dots());
    }
    if (box.dataset.active === "1") { running(); poll(0); }   // already going (the nightly one, or from another tab)
    start.addEventListener("click", function () {
      running();
      post(box.dataset.url).then(function (data) {
        if (!data.ok) { start.disabled = false; say(note, data.message || box.dataset.failed); return; }
        poll(0);
      }, function () { start.disabled = false; say(note, box.dataset.failed); });
    });
  });

  // --- putting a backup back: upload in pieces, open with the key, look at it, confirm, wait for the restart
  var PIECE = 8 * 1024 * 1024;
  document.querySelectorAll("[data-restore]").forEach(function (root) {
    var base = root.dataset.base;
    var de = root.dataset.de === "1";
    function mb(bytes) {
      var text = (bytes / 1e6).toFixed(bytes < 1e8 ? 1 : 0);
      return (de ? text.replace(".", ",") : text) + " MB";
    }
    function why(reason) { return root.getAttribute("data-err-" + reason) || root.dataset.failed; }
    function fail(reason) {
      root.querySelector("[data-restore-why]").textContent = why(reason);
      steps(root, "failed");
    }
    function stepError(step, text) {
      var box = root.querySelector('[data-step="' + step + '"] [data-error]');
      say(box, text);
    }

    var fileInput = root.querySelector("[data-restore-file]");
    var progress = root.querySelector("[data-restore-progress]");
    var bar = progress.querySelector(".rs-bar > i");
    var count = root.querySelector("[data-restore-count]");
    var pick = root.querySelector("[data-restore-pick]");
    pick.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      var file = fileInput.files[0];
      if (!file) return;
      pick.disabled = true;
      progress.hidden = false;
      AgentHub.hold(true);
      var tries = 0;
      function show(done) {
        bar.style.transform = "scaleX(" + Math.min(1, done / file.size) + ")";
        count.textContent = root.dataset.uploading.replace("{done}", mb(done)).replace("{total}", mb(file.size));
      }
      // One piece per request, with its own progress (a slow line still shows it moves). A piece that hangs is given
      // up after a while and sent again; the server says how much it has, so nothing is sent twice (27.11.2026).
      function send(offset) {
        show(offset);
        var piece = file.slice(offset, offset + PIECE);
        var xhr = new XMLHttpRequest();
        xhr.open("POST", base + "/upload?offset=" + offset + "&total=" + file.size);
        xhr.timeout = 300000;
        xhr.upload.onprogress = function (event) { show(offset + event.loaded); };
        xhr.onload = function () {
          var data = {};
          try { data = JSON.parse(xhr.responseText); } catch (e) {}
          if (data.ok && data.state === "done") { finished(); steps(root, "key"); return; }
          if (data.ok) { tries = 0; send(offset + piece.size); return; }
          if (data.reason === "offset" && typeof data.have === "number" && tries < 3) { tries += 1; send(data.have); return; }
          finished();
          fail(data.reason === "size" || data.reason === "busy" ? data.reason : "failed");
        };
        xhr.onerror = xhr.ontimeout = function () {
          if (tries < 3) { tries += 1; setTimeout(function () { send(offset); }, 3000); return; }
          finished();
          fail("failed");
        };
        xhr.send(piece);
      }
      function finished() { AgentHub.hold(false); pick.disabled = false; progress.hidden = true; fileInput.value = ""; }
      send(0);
    });

    var keyField = root.querySelector("[data-restore-key]");
    var keyFile = root.querySelector("[data-restore-keyfile]");
    root.querySelector("[data-restore-keypick]").addEventListener("click", function () { keyFile.click(); });
    keyFile.addEventListener("change", function () {
      var file = keyFile.files[0];
      if (!file || file.size > 10000) return;
      var reader = new FileReader();
      reader.onload = function () { keyField.value = String(reader.result || ""); keyFile.value = ""; };
      reader.readAsText(file);
    });

    function waitCheck(job, tries) {
      getJson(base + "/state?job=" + job).then(function (data) {
        if (data.stage === "checking" && tries < 1200) { setTimeout(function () { waitCheck(job, tries + 1); }, 2000); return; }
        if (data.stage === "failed") {
          if (data.upload && (data.reason === "wrong_key" || data.reason === "bad_key")) {
            steps(root, "key");
            stepError("key", why(data.reason));
          } else fail(data.reason || "failed");
          return;
        }
        show(data);
      }, function () { setTimeout(function () { waitCheck(job, tries + 1); }, 4000); });
    }
    root.querySelector("[data-restore-check]").addEventListener("click", function () {
      stepError("key", "");
      post(base + "/check", { key: keyField.value }).then(function (data) {
        if (!data.ok) { stepError("key", why(data.reason)); return; }
        keyField.value = "";
        steps(root, "checking");
        waitCheck(data.job, 0);
      }, function () { stepError("key", root.dataset.failed); });
    });

    function show(data) {
      if (data.stage !== "summary") { steps(root, data.stage === "key" ? "key" : "pick"); return; }
      Object.keys(data.summary).forEach(function (key) {
        var cell = root.querySelector('[data-fact="' + key + '"]');
        if (cell) cell.textContent = data.summary[key];
      });
      root.querySelector("[data-restore-tunnel]").hidden = !data.summary.tunnel;
      root.querySelector("[data-restore-apply]").disabled = !!data.newer;
      stepError("summary", data.newer ? why("newer") : "");
      steps(root, "summary");
    }

    function waitDone(tries) {
      // The hub stops and starts again; until then the requests fail. Then it says how it went.
      fetch("/restore/done", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.done === true) { steps(root, "done"); return; }
        if (data.done === false) { fail("apply"); return; }
        if (tries < 900) setTimeout(function () { waitDone(tries + 1); }, 3000);
      }, function () { if (tries < 900) setTimeout(function () { waitDone(tries + 1); }, 3000); });
    }
    root.querySelector("[data-restore-apply]").addEventListener("click", function () {
      var password = root.querySelector("[data-restore-password]");
      stepError("summary", "");
      post(base + "/apply", { confirm: password ? password.value : "" }).then(function (data) {
        if (!data.ok) { stepError("summary", data.message || why(data.reason)); return; }
        steps(root, "applying");
        setTimeout(function () { waitDone(0); }, 4000);
      }, function () { stepError("summary", root.dataset.failed); });
    });

    root.querySelectorAll("[data-restore-cancel]").forEach(function (button) {
      button.addEventListener("click", function () { post(base + "/cancel").then(function () { steps(root, "pick"); }); });
    });
    root.querySelector("[data-restore-again]").addEventListener("click", function () {
      getJson(base + "/state").then(show, function () { steps(root, "pick"); });
    });
    getJson(base + "/state").then(show, function () {});
  });
})();
