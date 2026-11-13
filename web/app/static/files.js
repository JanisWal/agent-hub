// Files and links in the Manager view: five areas as tabs (a sliding highlight like an iOS segmented control),
// upload in small chunks with speed and time left, several files at once under each other with a cross to cancel,
// drag files onto the tile (the tabs pop up and the one under the pointer takes the file) or paste them, drag a
// file out to the desktop or a folder (Chrome and Edge), rename or edit with one dialog (the pencil), delete after
// a confirmation. Needs core.js and motion.js.
//
// Upload: the proven way (tus, Uppy, Cloudflare Stream): small chunks (5 MiB, a multiple of 256 KiB), a failed
// chunk is sent again after growing pauses, the server is the source of truth (it keeps a flag per chunk), and the
// speed counts only bytes the server has confirmed (the browser's own progress also counts what it has merely
// queued, which looks fast at first and then falls). A request that runs too long is cut after 90 s here, before
// the tunnel's own limit of about 100 s cuts it for us.
(function () {
  var tile = document.getElementById("files");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var projectId = project.dataset.id;
  var CHUNK = parseInt(tile.dataset.chunk, 10);   // the size the server expects (files.CHUNK_SIZE)
  var PARALLEL = 2;                               // requests on their way at the same time, over all files
  var DELAYS = [0, 1000, 3000, 5000, 10000];      // pauses before each new try of a chunk (tus-js-client, Uppy)
  var STALL = 25000;                              // no progress for this long: give up on the request and try again
  var CANCELLED = new Error("cancelled");
  var tabsBox = tile.querySelector(".file-tabs");
  var tabs = Array.prototype.slice.call(tile.querySelectorAll(".file-tab"));
  var panels = Array.prototype.slice.call(tile.querySelectorAll(".file-list"));
  var scroller = tile.querySelector(".file-scroll");
  var thumb = tile.querySelector(".file-thumb");
  var area = tile.querySelector(".file-area");
  var addButton = document.getElementById("file-add");
  var picker = document.getElementById("file-picker");
  var errorBox = document.getElementById("file-error");
  var uploads = document.getElementById("file-uploads");
  var template = document.getElementById("file-up-template");
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
    }).then(function () { ensureThumbs(); }).catch(reload);
  }
  var refreshTimer = null;
  function refreshSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 300); }

  // --- small preview pictures (Janis, 13.11.2026): made in the browser, so the Pi does no image work and the list
  // never loads the originals. A picture or the first moments of a video are scaled down to a square of THUMB
  // pixels (JPEG) and kept by the server next to the file. New files get theirs right after the upload; older files
  // (and anything that failed) get theirs once when the list is first shown.
  var THUMB = 96;
  var thumbBusy = false;
  var thumbFailed = {};
  function drawThumb(element, width, height) {
    if (!width || !height) return Promise.resolve(null);
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = THUMB;
    var scale = Math.max(THUMB / width, THUMB / height);            // fill the square, crop the rest
    var w = THUMB / scale, h = THUMB / scale;
    canvas.getContext("2d").drawImage(element, (width - w) / 2, (height - h) / 2, w, h, 0, 0, THUMB, THUMB);
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.8); });
  }
  function thumbFromImage(src) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.onload = function () { resolve(drawThumb(image, image.naturalWidth, image.naturalHeight)); };
      image.onerror = function () { resolve(null); };
      image.src = src;
    });
  }
  function thumbFromVideo(src) {
    return new Promise(function (resolve) {
      var video = document.createElement("video");
      var timer = setTimeout(function () { finish(null); }, 20000);
      function finish(blob) { clearTimeout(timer); video.removeAttribute("src"); video.load(); resolve(blob); }
      video.muted = true;
      video.playsInline = true;
      video.preload = "metadata";
      video.onerror = function () { finish(null); };
      video.onloadedmetadata = function () { video.currentTime = Math.min(1, (video.duration || 2) / 4); };
      video.onseeked = function () { drawThumb(video, video.videoWidth, video.videoHeight).then(finish); };
      video.src = src;
    });
  }
  function sendThumb(id, blob) {
    return blob ? fetch("/files/" + id + "/thumb", { method: "POST", body: blob }).then(function (r) { return r.ok; }, function () { return false; }) : Promise.resolve(false);
  }
  function thumbOfUpload(job) {       // right after an upload we still hold the file itself
    var type = job.file.type || "";
    if (!/^(image|video)\//.test(type)) return Promise.resolve();
    var url = URL.createObjectURL(job.file);
    var made = type.indexOf("video/") === 0 ? thumbFromVideo(url) : thumbFromImage(url);
    return made.then(function (blob) { return sendThumb(job.id, blob); }).then(function () { URL.revokeObjectURL(url); }, function () { URL.revokeObjectURL(url); });
  }
  function ensureThumbs() {            // one at a time, for rows that were shown without a preview
    if (thumbBusy) return;
    var pending = tile.querySelector(".file-pending[data-need-thumb]");
    while (pending && thumbFailed[pending.closest(".file-row").dataset.id]) {
      pending.remove();
      pending = tile.querySelector(".file-pending[data-need-thumb]");
    }
    if (!pending) return;
    thumbBusy = true;
    var id = pending.closest(".file-row").dataset.id;
    var source = "/files/" + id;
    (pending.dataset.needThumb === "video" ? thumbFromVideo(source) : thumbFromImage(source))
      .then(function (blob) { return sendThumb(id, blob); })
      .then(function (okay) {
        if (okay && pending.isConnected) {
          var image = document.createElement("img");
          image.className = "file-preview";
          image.alt = "";
          image.draggable = false;
          image.src = "/files/" + id + "/thumb";
          pending.replaceWith(image);
        } else { thumbFailed[id] = true; pending.remove(); }
      })
      .catch(function () { thumbFailed[id] = true; })
      .then(function () { thumbBusy = false; ensureThumbs(); });
  }
  // A preview that cannot be loaded (a link's icon, a missing picture) simply disappears; the symbol stays.
  tile.addEventListener("error", function (event) {
    if (event.target.classList && event.target.classList.contains("file-preview")) event.target.remove();
  }, true);

  // --- tabs: the highlight slides under the chosen tab with a spring (it can be interrupted at any moment)
  var thumbX = Motion.spring(0, Motion.MOVE, function (x) { thumb.style.transform = "translateX(" + x + "px)"; }, 0.05);
  function placeThumb(instant) {
    var tab = tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0];
    if (!tab || !tab.offsetWidth) return;
    thumb.style.width = tab.offsetWidth + "px";
    if (instant) thumbX.set(tab.offsetLeft); else thumbX.to(tab.offsetLeft);
  }
  function show(category, instant) {
    active = category;
    tabs.forEach(function (tab) { tab.setAttribute("aria-selected", tab.dataset.cat === category ? "true" : "false"); });
    panels.forEach(function (panel) { panel.hidden = panel.dataset.cat !== category; });
    var name = tabs.filter(function (tab) { return tab.dataset.cat === category; })[0].dataset.name;
    area.textContent = " · " + name;             // "Dateien · Medien" while the tabs only show symbols
    var label = tile.dataset[category === "links" ? "addLink" : "addFile"];
    addButton.setAttribute("aria-label", label);
    addButton.title = label;
    placeThumb(instant);
    if (!instant) scroller.scrollTop = 0;              // a new tab starts at its top
    store("files-tab", category);
  }
  tabs.forEach(function (tab) { tab.addEventListener("click", function () { show(tab.dataset.cat); }); });
  var saved = load("files-tab");
  show(tabs.some(function (tab) { return tab.dataset.cat === saved; }) ? saved : active, true);
  if (window.ResizeObserver) new ResizeObserver(function () { placeThumb(true); }).observe(tabsBox);   // also when the view first shows

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

  // --- upload: a queue of files, a few requests at a time over all of them
  var jobs = [];
  var running = 0;
  var samples = [];        // [time, bytes the server has confirmed] over the last 20 s, for the speed
  var confirmed = 0;
  var ticker = null;

  function sendChunk(job, index, onProgress) {
    var start = index * CHUNK;
    var blob = job.file.slice(start, Math.min(start + CHUNK, job.file.size));
    return new Promise(function (resolve, reject) {
      var attempt = 0;
      function go() {
        if (job.cancelled) return reject(CANCELLED);
        var xhr = new XMLHttpRequest();
        var last = Date.now();
        var finished = false;
        var dog = setInterval(function () { if (Date.now() - last > STALL) xhr.abort(); }, 5000);
        function done() { finished = true; clearInterval(dog); job.xhrs.splice(job.xhrs.indexOf(xhr), 1); }
        function again() {
          if (finished) return;
          done();
          if (job.cancelled) return reject(CANCELLED);
          onProgress(0);
          if (attempt >= DELAYS.length) return reject(new Error(tile.dataset.errNet));
          setTimeout(go, DELAYS[attempt++]);
        }
        job.xhrs.push(xhr);
        xhr.open("POST", "/files/" + job.id + "/chunk?offset=" + start);
        xhr.timeout = 90000;
        xhr.upload.onprogress = function (event) { last = Date.now(); if (event.lengthComputable) onProgress(event.loaded); };
        xhr.onerror = xhr.ontimeout = xhr.onabort = again;
        xhr.onload = function () {
          if (finished) return;
          var data = {};
          try { data = JSON.parse(xhr.responseText); } catch (e) {}
          if (xhr.status === 200 && data.ok) { done(); resolve(); }
          else if ([408, 429, 502, 503, 504, 524].indexOf(xhr.status) >= 0) again();   // the tunnel hiccuped: try again
          else { done(); reject(new Error(data.message || tile.dataset.errNet)); }
        };
        xhr.send(blob);
      }
      go();
    });
  }

  function nextWork() {
    for (var n = 0; n < jobs.length; n++) {
      var job = jobs[n];
      if (job.state === "new") { job.state = "starting"; return function () { return startJob(job); }; }
      if (job.state === "sending" && job.next < job.count) {
        var index = job.next++;
        return function () { return sendJobChunk(job, index); };
      }
      if (job.state === "sending" && job.acked === job.count) { job.state = "finishing"; return function () { return finishJob(job); }; }
    }
    return null;
  }

  function pump() {
    var work;
    while (running < PARALLEL && (work = nextWork())) {
      running++;
      work().then(null, function () {}).then(function () { running--; pump(); });
    }
    if (!running && !jobs.some(function (job) { return ["new", "starting", "sending", "finishing"].indexOf(job.state) >= 0; })) allDone();
  }

  function startJob(job) {
    return call("/projects/" + projectId + "/files/start", fields({ name: job.file.name, size: job.file.size })).then(function (info) {
      job.id = info.id;
      if (job.cancelled) return call("/files/" + info.id + "/delete").catch(function () {});
      job.state = "sending";
    }, function (problem) { failJob(job, problem); });
  }

  function sendJobChunk(job, index) {
    var size = Math.min(CHUNK, job.file.size - index * CHUNK);
    return sendChunk(job, index, function (bytes) { job.loaded[index] = bytes; }).then(function () {
      job.loaded[index] = size;
      job.acked++;
      job.confirmed += size;
      confirmed += size;
      samples.push([Date.now(), confirmed]);
    }, function (problem) { failJob(job, problem); });
  }

  function finishJob(job) {
    return call("/files/" + job.id + "/finish").then(function (done) {
      if (job.category && job.category !== done.category) {
        return call("/files/" + done.id, fields({ name: done.name, category: job.category }));
      }
    }).then(function () { return thumbOfUpload(job); }).then(function () {
      job.state = "done";
      job.row.remove();
      refreshSoon();
    }, function (problem) { failJob(job, problem); });
  }

  function drop(job, state) {
    job.state = state;
    job.xhrs.slice().forEach(function (xhr) { xhr.abort(); });
    job.row.remove();
    if (job.id) call("/files/" + job.id + "/delete").catch(function () {});      // the unfinished file goes too
  }
  function failJob(job, problem) {
    if (job.cancelled || problem === CANCELLED || job.state === "failed") return;
    drop(job, "failed");
    say(errorBox, problem.message);
  }
  function cancelJob(job) {
    if (job.cancelled) return;
    job.cancelled = true;
    drop(job, "cancelled");
    pump();
  }

  function allDone() {
    if (!jobs.length) return;
    jobs = [];
    samples = [];
    confirmed = 0;
    clearInterval(ticker);
    ticker = null;
    uploads.hidden = true;
    refresh();
  }

  // Speed over the last 20 s of what the server confirmed, and the time that is left for the files up to this one.
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
  function tick() {
    var now = Date.now();
    while (samples.length > 1 && now - samples[0][0] > 20000) samples.shift();
    var speed = 0;
    if (samples.length) {
      var span = (now - Math.min(samples[0][0], now - 1000)) / 1000;
      var base = samples.length > 1 || now - samples[0][0] > 20000 ? samples[0][1] : 0;
      speed = (confirmed - base) / Math.max(span, 1);
    }
    var ahead = 0;
    jobs.forEach(function (job) {
      var sum = 0;
      job.loaded.forEach(function (bytes) { sum += bytes; });
      job.bar.style.transform = "scaleX(" + (job.file.size ? Math.min(sum / job.file.size, 1) : 1) + ")";
      ahead += job.file.size - job.confirmed;
      job.meta.textContent = speed > 0 && job.state !== "failed" ? formatSpeed(speed) + " · " + formatLeft(Math.round(ahead / speed)) : "";
    });
  }

  function addJobs(list, category) {
    list.forEach(function (file) {
      var row = template.content.firstElementChild.cloneNode(true);
      row.querySelector(".file-up-name").textContent = file.name;
      var job = {
        file: file, category: category, row: row, meta: row.querySelector(".file-up-meta"), bar: row.querySelector("i"),
        id: null, state: "new", count: Math.ceil(file.size / CHUNK), next: 0, acked: 0, confirmed: 0, loaded: [], xhrs: [], cancelled: false
      };
      for (var n = 0; n < job.count; n++) job.loaded.push(0);
      row.querySelector(".file-up-x").addEventListener("click", function () { cancelJob(job); });
      uploads.appendChild(row);          // every file gets its row at once, one under the other
      jobs.push(job);
    });
    say(errorBox, "");
    uploads.hidden = false;
    if (category) show(category);
    if (!ticker) ticker = setInterval(tick, 500);
    pump();
  }

  addButton.addEventListener("click", function () {
    if (active === "links") openDialog(null); else picker.click();
  });
  picker.addEventListener("change", function () {
    var list = Array.prototype.slice.call(picker.files);
    picker.value = "";
    if (list.length) addJobs(list, null);
  });

  // Files pasted with Ctrl+V or Cmd+V (not while writing in a field, and only while this view is showing).
  document.addEventListener("paste", function (event) {
    var target = event.target;
    var typing = target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
    var list = event.clipboardData ? Array.prototype.slice.call(event.clipboardData.files) : [];
    if (typing || !list.length || !tile.offsetParent) return;
    event.preventDefault();
    addJobs(list, null);
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
    if (list.length) addJobs(list, category);
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
    // The name downloads a file (its link says `?download=1`), opens a link in a new tab and opens the editor of a
    // text. The symbol and the preview open the viewer of a picture, video or sound; for anything else they do what
    // the name does (Janis, 13.11.2026: a click should download, not just open a new window).
    var name = event.target.closest(".file-text");
    var picture = event.target.closest(".file-tile, .file-preview");
    if (!row || (!name && !picture)) return;
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;   // with a key held the browser decides
    var viewable = ["image", "video", "audio"].indexOf(row.dataset.kind) >= 0;
    if (row.dataset.editable === "1") { event.preventDefault(); openDialog(row); }
    else if (picture && viewable) { event.preventDefault(); openViewer(row); }
    else if (picture && row.dataset.kind === "link") { window.open(row.dataset.url, "_blank", "noopener,noreferrer"); }
    else if (picture) { location.href = "/files/" + row.dataset.id + "?download=1"; }
  });

  // --- the viewer: a picture is shown, a video or sound gets a small player (Janis, 13.11.2026)
  var viewer = document.getElementById("file-viewer");
  var viewerBody = document.getElementById("file-viewer-body");
  var viewerTitle = document.getElementById("file-viewer-title");
  var viewerId = null;
  function openViewer(row) {
    var kind = row.dataset.kind;
    var node = document.createElement(kind === "image" ? "img" : kind);
    if (kind === "image") node.alt = ""; else { node.controls = true; node.preload = "metadata"; node.playsInline = true; }
    node.src = "/files/" + row.dataset.id;
    viewerBody.textContent = "";
    viewerBody.appendChild(node);
    viewerTitle.textContent = row.dataset.name;
    viewerId = row.dataset.id;
    viewer.showModal();
  }
  viewer.addEventListener("close", function () { viewerBody.textContent = ""; viewerId = null; });   // stops the player
  document.getElementById("file-viewer-download").addEventListener("click", function () {
    if (viewerId) location.href = "/files/" + viewerId + "?download=1";
  });

  ensureThumbs();

  document.getElementById("file-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    confirmDialog.close();
    if (id) call("/files/" + id + "/delete").then(refresh, refresh);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; });
})();
