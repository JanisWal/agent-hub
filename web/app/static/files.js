// Files and links in the Manager view: five areas as tabs, upload in chunks (plus button, or drag files onto the
// tile: the tabs pop up and the one under the pointer takes the file), rename or edit with one dialog (the
// pencil), delete after a confirmation. Needs core.js and motion.js.
(function () {
  var tile = document.getElementById("files");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var projectId = project.dataset.id;
  var CHUNK = 8 * 1024 * 1024;
  var tabs = Array.prototype.slice.call(tile.querySelectorAll(".file-tab"));
  var panels = Array.prototype.slice.call(tile.querySelectorAll(".file-list"));
  var addButton = document.getElementById("file-add");
  var picker = document.getElementById("file-picker");
  var errorBox = document.getElementById("file-error");
  var uploads = document.getElementById("file-uploads");
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

  function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) {} }
  function load(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
  function reload() { AgentHub.reload(); }
  function say(box, text) { box.textContent = text; box.hidden = !text; }

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
    }, function () { throw new Error(tile.dataset.errNet); });   // no network: the same message, so a chunk is tried again
  }
  function fields(values) {
    var body = new FormData();
    Object.keys(values).forEach(function (key) { body.append(key, values[key]); });
    return body;
  }

  // --- upload in chunks
  function sendChunks(id, file, offset, bar, tries) {
    if (offset >= file.size) return Promise.resolve();
    var end = Math.min(offset + CHUNK, file.size);
    return call("/files/" + id + "/chunk?offset=" + offset, file.slice(offset, end)).then(function () {
      bar.style.transform = "scaleX(" + (end / file.size) + ")";
      return sendChunks(id, file, end, bar, 3);
    }, function (problem) {
      if (tries > 0 && problem.message === tile.dataset.errNet) return sendChunks(id, file, offset, bar, tries - 1);
      throw problem;
    });
  }

  function uploadOne(file, category) {
    var row = document.createElement("li");
    row.className = "file-up";
    row.innerHTML = '<span class="file-up-name"></span><span class="file-bar"><i></i></span>';
    row.firstChild.textContent = file.name;
    var bar = row.querySelector("i");
    uploads.appendChild(row);
    uploads.hidden = false;
    var made;
    return call("/projects/" + projectId + "/files/start", fields({ name: file.name, size: file.size }))
      .then(function (info) { made = info; return sendChunks(info.id, file, 0, bar, 3); })
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
      if (problem) store("files-notice", problem);
      if (category) store("files-tab", category);
      reload();
    });
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
    tabs.forEach(function (other) {
      other.classList.toggle("hot", other === tab);
      pop(other, !dragging ? 1 : other === tab ? 1.16 : 1.06);
    });
  }
  function endDrag() {
    dragging = false;
    tile.classList.remove("dropping");
    hot = null;
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
    request.then(function () { store("files-tab", next); reload(); },
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
    if (id) call("/files/" + id + "/delete").then(reload, reload);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
