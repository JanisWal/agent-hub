// Files and links in the Manager view: five areas as tabs, upload in parallel chunks with speed and time left
// (plus button, or drag files onto the tile: the tabs pop up and the one under the pointer takes the file),
// drag a file out to the desktop or a folder (Chrome and Edge), rename or edit with one dialog (the pencil),
// delete after a confirmation. Needs core.js and motion.js.
(function () {
  var tile = document.getElementById("files");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var projectId = project.dataset.id;
  var CHUNK = parseInt(tile.dataset.chunk, 10);   // the size the server expects (files.CHUNK_SIZE)
  var PARALLEL = 3;                               // chunks on their way at the same time
  var tabs = Array.prototype.slice.call(tile.querySelectorAll(".file-tab"));
  var panels = Array.prototype.slice.call(tile.querySelectorAll(".file-list"));
  var addButton = document.getElementById("file-add");
  var picker = document.getElementById("file-picker");
  var errorBox = document.getElementById("file-error");
  var uploads = document.getElementById("file-uploads");
  var dropHint = tile.querySelector(".file-drop");
  var dropText = dropHint.textContent;
  var dialog = document.getElementById("file-dialog");
  var form = dialog.querySelector("form");
  var nameInput = form.querySelector('input[name="name"]');
  var urlBox = document.getElementById("file-url-box");
  var urlInput = form.querySelector('input[name="url"]');
  var areaBox = document.getElementById("file-area-box");
  var areaSelect = form.querySelector('select[name="category"]');
  var textBox = document.getElementById("file-text-box");
  var textInput = form.querySelector('textarea[name="text"]');
  var dialogError = document.getElementById("file-dialog-error");
  var confirmDialog = document.getElementById("file-confirm");
  var active = "memory";
  var editing = null;        // the row being edited, or null for a new link
  var textLoaded = false;
  var pendingId = null;
  var lang = document.documentElement.lang || "de";

  function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) {} }
  function load(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
  function reload() { AgentHub.reload(); }
  function say(box, text) { box.textContent = text; box.hidden = !text; }

  // After an upload, a change or a delete only the lists and counters of this tile are swapped (the new page is
  // fetched and read, nothing is reloaded), so nothing flickers. If that fails, the page reloads as a fallback.
  function refresh() {
    return fetch(location.pathname, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("refresh");
      return response.text();
    }).then(function (html) {
      var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("files");
      if (!fresh) throw new Error("refresh");
      panels.forEach(function (panel) {
        var next = fresh.querySelector('.file-list[data-cat="' + panel.dataset.cat + '"]');
        if (next) panel.innerHTML = next.innerHTML;
      });
      tabs.forEach(function (tab) {
        var next = fresh.querySelector('.file-tab[data-cat="' + tab.dataset.cat + '"] .file-count');
        if (next) tab.querySelector(".file-count").textContent = next.textContent;
      });
    }).catch(reload);
  }

  // --- tabs
  function show(category) {
    active = category;
    tabs.forEach(function (tab) { tab.setAttribute("aria-selected", tab.dataset.cat === category ? "true" : "false"); });
    panels.forEach(function (panel) { panel.hidden = panel.dataset.cat !== category; });
    var label = tile.dataset[category === "links" ? "addLink" : "addFile"];
    addButton.setAttribute("aria-label", label);
    addButton.title = label;
    store("files-tab", category);
  }
  tabs.forEach(function (tab) { tab.addEventListener("click", function () { show(tab.dataset.cat); }); });
  var saved = load("files-tab");
  show(tabs.some(function (tab) { return tab.dataset.cat === saved; }) ? saved : active);

  var notice = load("files-notice");
  if (notice) { say(errorBox, notice); store("files-notice", ""); }

  // --- calls
  function call(url, body, method) {
    return fetch(url, { method: method || "POST", body: body }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || !data.ok) throw new Error(data.message || tile.dataset.errNet);
        return data;
      });
    }, function () { throw new Error(tile.dataset.errNet); });
  }
  function fields(values) {
    var body = new FormData();
    Object.keys(values).forEach(function (key) { body.append(key, values[key]); });
    return body;
  }

  // --- upload: chunks of CHUNK bytes, PARALLEL at a time, each can go in any order and be sent again
  function sendChunk(id, blob, offset, onProgress, tries) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      function again() {
        if (tries > 0) { onProgress(0); sendChunk(id, blob, offset, onProgress, tries - 1).then(resolve, reject); }
        else reject(new Error(tile.dataset.errNet));
      }
      xhr.open("POST", "/files/" + id + "/chunk?offset=" + offset);
      xhr.upload.onprogress = function (event) { if (event.lengthComputable) onProgress(event.loaded); };
      xhr.onerror = again;
      xhr.onload = function () {
        var data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) {}
        if (xhr.status === 200 && data.ok) resolve();
        else if ([502, 503, 504, 524].indexOf(xhr.status) >= 0) again();   // the tunnel hiccuped: try this chunk again
        else reject(new Error(data.message || tile.dataset.errNet));
      };
      xhr.send(blob);
    });
  }

  function sendAll(id, file, onBytes) {
    var count = Math.ceil(file.size / CHUNK);
    var loaded = [];
    var next = 0;
    var failed = null;
    for (var n = 0; n < count; n++) loaded.push(0);
    function worker() {
      if (failed || next >= count) return Promise.resolve();
      var index = next++;
      var start = index * CHUNK;
      var end = Math.min(start + CHUNK, file.size);
      return sendChunk(id, file.slice(start, end), start, function (bytes) {
        loaded[index] = bytes;
        onBytes(loaded.reduce(function (sum, value) { return sum + value; }, 0));
      }, 3).then(function () {
        loaded[index] = end - start;
        onBytes(loaded.reduce(function (sum, value) { return sum + value; }, 0));
        return worker();
      }, function (problem) { failed = problem; throw problem; });
    }
    var running = [];
    for (var w = 0; w < Math.min(PARALLEL, count); w++) running.push(worker());
    return Promise.all(running);
  }

  // Speed over the last few seconds, and the time that is left for it.
  function meter() {
    var samples = [];
    return function (bytes, total) {
      var now = Date.now();
      samples.push({ t: now, b: bytes });
      while (samples.length > 2 && now - samples[0].t > 4000) samples.shift();
      var first = samples[0];
      var span = (now - first.t) / 1000;
      if (span < 0.8 || bytes <= first.b) return Math.round(100 * bytes / Math.max(total, 1)) + " %";
      var speed = (bytes - first.b) / span;
      var left = Math.max(0, Math.round((total - bytes) / speed));
      return Math.round(100 * bytes / Math.max(total, 1)) + " % · " + formatSpeed(speed) + " · " + formatLeft(left);
    };
  }
  function formatSpeed(bytesPerSecond) {
    var mb = bytesPerSecond / 1048576;
    var value = mb >= 1 ? mb : bytesPerSecond / 1024;
    return value.toLocaleString(lang, { maximumFractionDigits: value >= 10 ? 0 : 1 }) + (mb >= 1 ? " MB/s" : " KB/s");
  }
  function formatLeft(seconds) {
    if (seconds < 90) return tile.dataset.etaS.replace("{n}", Math.max(seconds, 1));
    if (seconds < 5400) return tile.dataset.etaM.replace("{n}", Math.round(seconds / 60));
    return tile.dataset.etaH.replace("{n}", (seconds / 3600).toLocaleString(lang, { maximumFractionDigits: 1 }));
  }

  function uploadOne(file, category) {
    var row = document.createElement("li");
    row.className = "file-up";
    row.innerHTML = '<span class="file-up-name"></span><span class="file-up-meta"></span><span class="file-bar"><i></i></span>';
    row.children[0].textContent = file.name;
    var meta = row.children[1];
    var bar = row.querySelector("i");
    uploads.appendChild(row);
    uploads.hidden = false;
    var measure = meter();
    var shown = 0;
    var made;
    return call("/projects/" + projectId + "/files/start", fields({ name: file.name, size: file.size }))
      .then(function (info) {
        made = info;
        return sendAll(info.id, file, function (bytes) {
          bar.style.transform = "scaleX(" + (bytes / Math.max(file.size, 1)) + ")";
          var now = Date.now();
          if (now - shown > 250) { shown = now; meta.textContent = measure(bytes, file.size); }
        });
      })
      .then(function () { return call("/files/" + made.id + "/finish"); })
      .then(function (done) {
        if (category && category !== done.category) {
          return call("/files/" + done.id, fields({ name: done.name, category: category }));
        }
      })
      .then(function () { row.remove(); }, function (problem) { row.remove(); throw problem; });
  }

  function uploadAll(list, category) {
    var problem = "";
    var chain = Promise.resolve();
    list.forEach(function (file) {
      chain = chain.then(function () { return uploadOne(file, category); }).catch(function (e) { problem = e.message; });
    });
    chain.then(function () {
      say(errorBox, problem);
      if (category) show(category);
      return refresh();
    }).then(function () { uploads.hidden = !uploads.children.length; });
  }

  addButton.addEventListener("click", function () {
    if (active === "links") openDialog(null); else picker.click();
  });
  picker.addEventListener("change", function () {
    var list = Array.prototype.slice.call(picker.files);
    picker.value = "";
    if (list.length) uploadAll(list, null);
  });

  // --- drag files onto the tile: the tabs pop up like glass drops, the one under the pointer pops more
  function pop(tab, scale) {
    if (!tab.__pop) tab.__pop = Motion.spring(1, Motion.LIFT, function (v) { tab.style.transform = "scale(" + v + ")"; }, 0.002);
    tab.__pop.to(scale);
  }
  var hot = null;
  var dragging = false;
  function hasFiles(event) { return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") >= 0; }
  function setHot(tab) {
    if (tab === hot && dragging) return;
    hot = tab;
    dropHint.textContent = tab ? tile.dataset.dropTo.replace("{name}", tab.dataset.name) : dropText;
    tabs.forEach(function (other) {
      other.classList.toggle("hot", other === tab);
      pop(other, !dragging ? 1 : other === tab ? 1.16 : 1.06);
    });
  }
  function endDrag() {
    dragging = false;
    tile.classList.remove("dropping");
    hot = null;
    dropHint.textContent = dropText;
    tabs.forEach(function (tab) { tab.classList.remove("hot"); pop(tab, 1); });
  }
  tile.addEventListener("dragover", function (event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dragging = true;
    tile.classList.add("dropping");
    setHot(event.target.closest ? event.target.closest(".file-tab") : null);
  });
  tile.addEventListener("dragleave", function (event) {
    if (!tile.contains(event.relatedTarget)) endDrag();
  });
  tile.addEventListener("drop", function (event) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    var category = hot ? hot.dataset.cat : null;
    var list = Array.prototype.slice.call(event.dataTransfer.files);
    endDrag();
    if (list.length) uploadAll(list, category);
  });

  // --- drag a file out of the tile onto the desktop or a folder: the browser downloads it there (Chrome and
  // Edge understand "DownloadURL"; Safari and Firefox do not and simply do nothing). A link drags its address.
  tile.addEventListener("dragstart", function (event) {
    var row = event.target.closest ? event.target.closest(".file-row") : null;
    if (!row) return;
    if (row.dataset.kind === "link") {
      event.dataTransfer.setData("text/uri-list", row.dataset.url);
      event.dataTransfer.setData("text/plain", row.dataset.url);
    } else {
      var url = location.origin + "/files/" + row.dataset.id;
      event.dataTransfer.setData("DownloadURL", "application/octet-stream:" + row.dataset.name + ":" + url);
    }
    event.dataTransfer.effectAllowed = "copy";
  });

  // --- the dialog: new link, rename, move, edit text
  function openDialog(row) {
    editing = row;
    var link = !row || row.dataset.kind === "link";
    var text = !!row && row.dataset.editable === "1";
    dialog.querySelector("h2").textContent = dialog.dataset[!row ? "titleLink" : link ? "titleEditLink" : "titleEdit"];
    document.getElementById("file-dialog-button").textContent = dialog.dataset[row ? "btnEdit" : "btnNew"];
    nameInput.value = row ? row.dataset.name : "";
    urlInput.value = row ? row.dataset.url || "" : "";
    urlBox.hidden = !link;
    urlInput.required = link;
    areaBox.hidden = link;
    areaSelect.value = row ? row.dataset.cat : active;
    textBox.hidden = !text;
    textInput.value = "";
    textLoaded = !text;
    say(dialogError, "");
    dialog.showModal();
    (link && !row ? urlInput : nameInput).focus();
    if (text) {
      call("/files/" + row.dataset.id + "/text", null, "GET").then(function (data) {
        textInput.value = data.text;
        textLoaded = true;
      }, function (problem) { say(dialogError, problem.message); });
    }
  }
  dialog.addEventListener("close", function () { form.reset(); AgentHub.clear(form); say(dialogError, ""); editing = null; });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!textLoaded) return;
    var request;
    var next = !editing || editing.dataset.kind === "link" ? "links" : areaSelect.value;   // the tab to show afterwards
    if (!editing) {
      request = call("/projects/" + projectId + "/links", fields({ url: urlInput.value, name: nameInput.value }));
    } else {
      var values = { name: nameInput.value };
      if (editing.dataset.kind === "link") values.url = urlInput.value; else values.category = areaSelect.value;
      request = call("/files/" + editing.dataset.id, fields(values));
      if (editing.dataset.editable === "1") {
        var id = editing.dataset.id;
        request = request.then(function () { return call("/files/" + id + "/text", fields({ text: textInput.value })); });
      }
    }
    request.then(function () { show(next); dialog.close(); return refresh(); },
      function (problem) { say(dialogError, problem.message); });
  });

  // --- rows: pencil (or a click on a text file) edits, the bin asks first
  tile.addEventListener("click", function (event) {
    var button = event.target.closest("[data-file]");
    var row = event.target.closest(".file-row");
    if (button && row) {
      if (button.dataset.file === "edit") {
        openDialog(row);
      } else {
        pendingId = row.dataset.id;
        confirmDialog.querySelector("h2").textContent = confirmDialog.dataset[row.dataset.kind === "link" ? "textLink" : "textFile"];
        confirmDialog.showModal();
      }
      return;
    }
    var open = event.target.closest(".file-text");
    if (open && row && row.dataset.editable === "1") { event.preventDefault(); openDialog(row); }
  });

  document.getElementById("file-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    confirmDialog.close();
    if (id) call("/files/" + id + "/delete").then(refresh, refresh);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
