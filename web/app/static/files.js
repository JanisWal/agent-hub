// Files and links in the Manager view: five areas as tabs (a sliding highlight like an iOS segmented control),
// upload with requests sized to the line, several files at once under each other with a cross to cancel, drag files
// onto the tile (the tabs pop up and the one under the pointer takes the file) or paste them, drag a file out to the
// desktop or a folder (Chrome and Edge), the pencil renames and moves, a click opens a big reader for Markdown and text
// or a viewer for pictures, video and sound, delete after a confirmation. Needs core.js and motion.js.
//
// The upload itself is upload.js (pieces, resume, retries); its settings come from the administration page. Before an
// upload the server says which names already exist in the area; then a dialog asks: keep both, replace or skip.
(function () {
  var tile = document.getElementById("files");
  var project = document.querySelector(".project");
  if (!tile || !project) return;
  var projectId = project.dataset.id;
  var BLOCK = parseInt(tile.dataset.block, 10);   // the unit the server counts in (files.BLOCK_SIZE)
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
  var statusBox = document.getElementById("file-status");
  var dropText = tile.dataset.drop;
  var dialog = document.getElementById("file-dialog");
  var form = dialog.querySelector("form");
  var nameInput = form.querySelector('input[name="name"]');
  var urlBox = document.getElementById("file-url-box");
  var urlInput = form.querySelector('input[name="url"]');
  var areaBox = document.getElementById("file-area-box");
  var areaSelect = form.querySelector('select[name="category"]');
  var dialogError = document.getElementById("file-dialog-error");
  var confirmDialog = document.getElementById("file-confirm");
  var active = "memory";
  var editing = null;        // the row in the pencil dialog, or null for a new link
  var pendingId = null;
  var pendingMany = null;     // ids waiting for the answer to "delete these?"
  var selected = {};          // ids marked (shift click: a range, ctrl or cmd click: one)
  var anchorId = null;        // the row a shift click counts the range from
  var lang = document.documentElement.lang || "de";

  function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) {} }
  function load(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
  function reload() { AgentHub.reload(); }
  function say(box, text) { box.textContent = text; box.hidden = !text; }

  // The status line at the foot of the tile: one line with its own place, so nothing moves when it speaks. It says, in
  // this order of importance, where a dragged file lands, a note about what a circle just did, or how many are marked.
  // A new text rises in with a spring and the line fades out when there is nothing to say.
  var dragText = "";
  var flashText = "";
  var flashTimer = null;
  var statusNow = "";
  var statusSpring = Motion.spring(0, Motion.MOVE, function (v) {
    statusBox.style.opacity = String(Math.max(0, Math.min(1, v)));
    statusBox.style.transform = "translateY(" + ((1 - v) * 5) + "px)";
  }, 0.002);
  function renderStatus() {
    var marked = Object.keys(selected).length;
    var text = dragText || flashText || (marked ? tile.dataset.marked.replace("{n}", marked) : "");
    if (text === statusNow) return;
    statusNow = text;
    if (text) { statusBox.textContent = text; statusSpring.set(0); statusSpring.to(1); }
    else statusSpring.to(0);
  }
  function flash(text) {
    flashText = text;
    renderStatus();
    clearTimeout(flashTimer);
    flashTimer = setTimeout(function () { flashText = ""; renderStatus(); }, 3500);
  }


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
    }).then(function () { if (typeof showMarks === "function") showMarks(); ensureThumbs(); }).catch(reload);
  }
  var refreshTimer = null;
  function refreshSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 300); }

  // --- small preview pictures: made in the browser, so the Pi does no image work and the list never loads the
  // originals. A picture or the first moments of a video are scaled down to a square of THUMB pixels (JPEG) and kept
  // by the server next to the file. New files get theirs right after the upload; older files (and anything that
  // failed) get theirs once when the list is first shown.
  var THUMB = 96;
  var PHOTO = /\.(tiff?|heic|heif|dng|cr2|cr3|nef|nrw|arw|srf|sr2|orf|rw2|raf|pef|srw|x3f|3fr|erf|kdc|mos|mrw)$/i;   // files.PHOTO
  var thumbBusy = false;
  var thumbFailed = {};
  function drawThumb(element, width, height, turn) {
    if (!width || !height) return Promise.resolve(null);
    var canvas = document.createElement("canvas");
    canvas.width = canvas.height = THUMB;
    var scale = Math.max(THUMB / width, THUMB / height);            // fill the square, crop the rest
    var w = THUMB / scale, h = THUMB / scale;
    var context = canvas.getContext("2d");
    var angle = { 3: Math.PI, 6: Math.PI / 2, 8: -Math.PI / 2 }[turn];   // the camera's orientation (TIFF, DNG)
    if (angle) { context.translate(THUMB / 2, THUMB / 2); context.rotate(angle); context.translate(-THUMB / 2, -THUMB / 2); }
    context.drawImage(element, (width - w) / 2, (height - h) / 2, w, h, 0, 0, THUMB, THUMB);
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.8); });
  }
  function thumbFromImage(src, turn) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.onload = function () { resolve(drawThumb(image, image.naturalWidth, image.naturalHeight, turn)); };
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
  // TIFF, HEIC and camera raw files (DNG, CR2, NEF, ...): Safari draws TIFF and HEIC itself; for the rest the small
  // TIFF reader (tiffthumb.js) takes the preview the camera put inside, or the pixels of a plain TIFF. First only the
  // start of the file is fetched (where the previews usually are), the whole file only if that was not enough.
  var PHOTO_TYPE = { tif: "image/tiff", tiff: "image/tiff", heic: "image/heic", heif: "image/heif" };
  var PHOTO_MAX = 300 * 1024 * 1024;
  function withUrl(blob, use) {
    var url = URL.createObjectURL(blob);
    return use(url).then(function (made) { URL.revokeObjectURL(url); return made; },
                         function () { URL.revokeObjectURL(url); return null; });
  }
  function photoFrom(buffer, type) {
    return window.HubTiff.preview(buffer).then(function (found) {
      if (found && found.blob) return withUrl(found.blob, function (url) { return thumbFromImage(url, found.turn); });
      if (found && found.image) {
        var canvas = document.createElement("canvas");
        canvas.width = found.image.width;
        canvas.height = found.image.height;
        canvas.getContext("2d").putImageData(found.image, 0, 0);
        return drawThumb(canvas, canvas.width, canvas.height, found.turn);
      }
      return withUrl(new Blob([buffer], { type: type }), function (url) { return thumbFromImage(url); });
    });
  }
  function thumbFromPhoto(src, name, file) {
    var type = PHOTO_TYPE[(name.split(".").pop() || "").toLowerCase()] || "application/octet-stream";
    if (file) return file.size <= PHOTO_MAX ? file.arrayBuffer().then(function (b) { return photoFrom(b, type); }) : Promise.resolve(null);
    return fetch(src, { headers: { Range: "bytes=0-16777215" }, credentials: "same-origin" }).then(function (head) {
      if (!head.ok) return null;
      var total = head.status === 206 ? parseInt((head.headers.get("Content-Range") || "").split("/")[1], 10) : 0;
      return head.arrayBuffer().then(function (start) { return photoFrom(start, type); }).then(function (made) {
        if (made || head.status !== 206 || !(total <= PHOTO_MAX)) return made;
        return fetch(src, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.arrayBuffer() : null; })
          .then(function (whole) { return whole ? photoFrom(whole, type) : null; });
      });
    });
  }
  function sendThumb(id, blob) {
    return blob ? fetch("/files/" + id + "/thumb", { method: "POST", body: blob }).then(function (r) { return r.ok; }, function () { return false; }) : Promise.resolve(false);
  }
  function thumbOfUpload(job) {       // right after an upload we still hold the file itself
    var type = job.file.type || "";
    if (PHOTO.test(job.file.name)) {
      return thumbFromPhoto(null, job.file.name, job.file).then(function (blob) { return sendThumb(job.id, blob); });
    }
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
    var row = pending.closest(".file-row");
    var kind = pending.dataset.needThumb;
    (kind === "video" ? thumbFromVideo(source) : kind === "photo" ? thumbFromPhoto(source, row.dataset.name)
      : thumbFromImage(source))
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

  // --- tabs: the shared segment slider (segment.js): the highlight springs under the chosen tab, and the chosen tab
  // can be dragged to another one (Janis, 14.11.2026)
  var segment = Segment.attach(tabsBox, {
    thumb: thumb,
    items: function () { return tabs; },
    current: function () { return tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0]; },
    pick: function (tab) { show(tab.dataset.cat); }
  });
  function placeThumb(instant) { segment.place(instant); }
  function show(category, instant) {
    active = category;
    tabs.forEach(function (tab) { tab.setAttribute("aria-selected", tab.dataset.cat === category ? "true" : "false"); });
    panels.forEach(function (panel) { panel.hidden = panel.dataset.cat !== category; });
    var name = tabs.filter(function (tab) { return tab.dataset.cat === category; })[0].dataset.name;
    area.textContent = " · " + name;             // "Dateien · Medien" while the tabs only show symbols
    var label = tile.dataset[category === "links" ? "addLink" : "addFile"];
    addButton.setAttribute("aria-label", label);
    addButton.dataset.tip = label;                    // our own tooltip (core.js), never `title`: that is the browser's grey box
    placeThumb(instant);
    if (!instant) scroller.scrollTop = 0;              // a new tab starts at its top
    store("files-tab", category);
  }
  tabs.forEach(function (tab) { tab.addEventListener("click", function () { show(tab.dataset.cat); }); });
  var saved = load("files-tab");
  show(tabs.some(function (tab) { return tab.dataset.cat === saved; }) ? saved : active, true);   // segment.js follows resizes

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

  // --- upload: the engine is upload.js (resume after a break, request sizes by the measured speed, retries); this
  // part only shows it: a row for every file at once, speed and time left, a cross to cancel
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
  function nothing() {}
  window.__uploadLog = [];   // every request with its time: for finding out where a slow upload is slow (console: __uploadLog)
  var holding = false;
  var uploader = HubUpload.create({
    block: BLOCK,
    scope: projectId,
    config: {                            // the owner's choice for the server (administration page, "Upload")
      parallel: parseInt(tile.dataset.parallel, 10) || HubUpload.DEFAULTS.parallel,
      maxRequest: parseInt(tile.dataset.maxRequest, 10) || HubUpload.DEFAULTS.maxRequest
    },
    urls: {
      start: "/projects/" + projectId + "/files/start",
      progress: function (id) { return "/files/" + id + "/progress"; },
      chunk: function (id) { return "/files/" + id + "/chunk"; },
      finish: function (id) { return "/files/" + id + "/finish"; },
      remove: function (id) { return "/files/" + id + "/delete"; }
    },
    text: { net: tile.dataset.errNet },
    onAdd: function (job) {
      if (!holding) { holding = true; AgentHub.hold(true); }   // no reload of the page while files go up
      var row = template.content.firstElementChild.cloneNode(true);
      row.querySelector(".file-up-name").textContent = job.meta.name || job.file.name;
      job.meta.row = row;
      job.meta.status = row.querySelector(".file-up-meta");
      job.meta.bar = row.querySelector("i");
      job.meta.status.textContent = tile.dataset.starting;       // there is something to read from the first moment
      row.querySelector(".file-up-x").addEventListener("click", function () { uploader.cancel(job); });
      uploads.appendChild(row);
      uploads.hidden = false;
    },
    onProgress: function (job, info) {
      job.meta.bar.style.transform = "scaleX(" + (info.size ? Math.min(info.sent / info.size, 1) : 1) + ")";
      job.meta.status.textContent = info.waiting ? tile.dataset.waiting
        : info.speed > 0 && info.left !== null ? formatSpeed(info.speed) + " \u00b7 " + formatLeft(info.left) : tile.dataset.starting;
    },
    onRequest: function (job, info) {
      window.__uploadLog.push({ file: job.file.name, offset: info.offset, bytes: info.length, ms: info.ms, attempt: info.attempt });
      if (window.console && console.debug) console.debug("upload", job.file.name, info);
    },
    onDone: function (job, info) {      // moves to the chosen area, replaces the old file, makes the preview; none may fail the upload
      var move = job.meta.category && job.meta.category !== info.category
        ? call("/files/" + info.id, fields({ name: info.name, category: job.meta.category })).catch(nothing) : Promise.resolve();
      return move.then(function () {                         // the old file goes only now that the new one is complete
        return Promise.all((job.meta.replace || []).map(function (id) { return call("/files/" + id + "/delete").catch(nothing); }));
      }).then(function () { return thumbOfUpload({ file: job.file, id: job.id }); }).catch(nothing);
    },
    onFinished: function (job) { job.meta.row.remove(); refreshSoon(); },
    onFail: function (job, message) { job.meta.row.remove(); say(errorBox, message); },
    onCancel: function (job) { job.meta.row.remove(); },
    onIdle: function () {
      uploads.hidden = true;
      if (holding) { holding = false; AgentHub.hold(false); }
      refresh();
    }
  });

  // --- same names (Janis, 13.11.2026): the server says which names the area already has (and a free name for each);
  // the dialog asks once for all of them. Closing it (Escape) skips them, like "Skip".
  var sameDialog = document.getElementById("file-same");
  var sameResolve = null;
  function askSame(taken) {
    document.getElementById("file-same-text").textContent = taken.length > 1 ? sameDialog.dataset.many : sameDialog.dataset.one;
    var names = document.getElementById("file-same-list");
    names.textContent = "";
    taken.forEach(function (hit) { var li = document.createElement("li"); li.textContent = hit.name; names.appendChild(li); });
    return new Promise(function (resolve) { sameResolve = resolve; sameDialog.showModal(); });
  }
  function answerSame(choice) {
    var resolve = sameResolve;
    sameResolve = null;
    if (sameDialog.open) sameDialog.close();
    if (resolve) resolve(choice);
  }
  sameDialog.addEventListener("click", function (event) {
    var button = event.target.closest("[data-same]");
    if (button) answerSame(button.dataset.same);
  });
  sameDialog.addEventListener("close", function () { answerSame("skip"); });

  function startJobs(list, category, taken, choice) {
    var hits = taken.slice();
    var replaced = {};
    list.forEach(function (file) {
      var at = -1;
      for (var i = 0; i < hits.length && at < 0; i++) if (hits[i].name === file.name) at = i;
      if (at < 0) return uploader.add(file, { category: category });
      var hit = hits.splice(at, 1)[0];
      if (choice === "skip") return;
      var ids = hit.ids.filter(function (id) { return !replaced[id]; });
      if (choice === "replace" && ids.length) {
        ids.forEach(function (id) { replaced[id] = true; });
        return uploader.add(file, { category: category, replace: ids });
      }
      uploader.add(file, { category: category, name: hit.free });    // keep both (or a second copy within this upload)
    });
  }

  function addJobs(list, category) {
    say(errorBox, "");
    if (category) show(category);
    var body = new FormData();
    list.forEach(function (file) { body.append("names", file.name); });
    if (category) body.append("category", category);
    call("/projects/" + projectId + "/files/check", body)
      .then(function (data) { return data.taken || []; }, function () { return []; })   // the check failing must not stop an upload
      .then(function (taken) {
        if (!taken.length) return startJobs(list, category, [], null);
        return askSame(taken).then(function (choice) { startJobs(list, category, taken, choice); });
      });
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
    dragText = tab ? tile.dataset.dropTo.replace("{name}", tab.dataset.name) : dropText;
    renderStatus();
    tabs.forEach(function (other) {
      other.classList.toggle("hot", other === tab);
      pop(other, !dragging ? 1 : other === tab ? 1.16 : 1.06);
    });
  }
  function endDrag() {
    dragging = false;
    tile.classList.remove("dropping");
    hot = null;
    dragText = "";
    renderStatus();
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

  // --- drag files out of the tile onto the desktop or a folder: the browser downloads them there (Chrome and Edge
  // understand "DownloadURL"; Safari and Firefox do not and simply do nothing). "DownloadURL" carries one file only, so
  // several marked files come as one ZIP that the server makes while sending (like Google Drive). Links drag addresses.
  // Several rows dragged out flow together into the pointer like a stack in the Finder (Janis, 13.11.2026): each row
  // glides to the grip and fades (spring MOVE, a wave by distance as with the tiles), the picture under the pointer is a
  // small stack with the count; when the drag ends they spring back. Only transform and opacity; interruptible.
  var gathered = [];
  function gatherShow(row, p) {
    if (p < 0.001) { row.style.transform = ""; row.style.opacity = ""; return; }
    row.style.transform = "translate(" + (row.__dx * p) + "px," + (row.__dy * p) + "px) scale(" + (1 - 0.3 * p) + ")";
    row.style.opacity = String(1 - 0.9 * p);
  }
  function gather(rows, x, y) {
    gathered = rows;
    rows.forEach(function (r) {
      var box = r.getBoundingClientRect();
      r.__dx = x - (box.left + box.width / 2);
      r.__dy = y - (box.top + box.height / 2);
      if (!r.__gather) r.__gather = Motion.spring(0, Motion.MOVE, function (p) { gatherShow(r, p); }, 0.002);
      clearTimeout(r.__gatherTimer);
      r.__gatherTimer = setTimeout(function () { r.__gather.to(1); }, Math.min(110, Math.hypot(r.__dx, r.__dy) / 10));
    });
  }
  function release() {
    gathered.forEach(function (r) { clearTimeout(r.__gatherTimer); if (r.__gather) r.__gather.to(0); });
    gathered = [];
  }
  function dragStack(rows) {
    var stack = document.createElement("div");
    stack.className = "file-drag-stack";
    rows.slice(0, 3).reverse().forEach(function (r, i, all) {   // the first row lies on top
      var card = document.createElement("div");
      var depth = all.length - 1 - i;
      card.className = "file-drag-card";
      card.textContent = r.dataset.name;
      card.style.transform = "translate(" + (depth * 5) + "px," + (depth * 5) + "px) rotate(" + [0, -3, 3][depth] + "deg)";
      stack.appendChild(card);
    });
    var count = document.createElement("span");
    count.className = "file-drag-count";
    count.textContent = rows.length;
    stack.appendChild(count);
    document.body.appendChild(stack);
    setTimeout(function () { stack.remove(); }, 0);              // the browser took its picture already
    return stack;
  }
  tile.addEventListener("dragend", release);

  tile.addEventListener("dragstart", function (event) {
    var row = event.target.closest ? event.target.closest(".file-row") : null;
    if (!row) return;
    var rows = row.classList.contains("selected") ? Array.prototype.slice.call(tile.querySelectorAll(".file-row.selected")) : [row];
    var fileRows = rows.filter(function (r) { return r.dataset.kind !== "link"; });
    var carried = fileRows.length > 1 ? fileRows : !fileRows.length && rows.length > 1 ? rows : null;
    if (carried) {
      event.dataTransfer.setDragImage(dragStack(carried), 28, 22);
      gather(carried, event.clientX, event.clientY);
    }
    if (fileRows.length > 1) {
      var zipName = tile.dataset.zipName.replace("{n}", fileRows.length) + ".zip";
      event.dataTransfer.setData("DownloadURL", "application/zip:" + zipName + ":" + location.origin +
                                 zipUrl(fileRows.map(function (r) { return r.dataset.id; })));
    } else if (fileRows.length === 1) {
      event.dataTransfer.setData("DownloadURL", "application/octet-stream:" + fileRows[0].dataset.name + ":" +
                                 location.origin + "/files/" + fileRows[0].dataset.id);
    } else {
      var urls = rows.map(function (r) { return r.dataset.url; }).join("\r\n");
      event.dataTransfer.setData("text/uri-list", urls);
      event.dataTransfer.setData("text/plain", urls);
    }
    event.dataTransfer.effectAllowed = "copy";
  });

  // --- the pencil dialog: a new link, or rename and move (the content is read and edited in the reader)
  function openDialog(row) {
    editing = row;
    var link = !row || row.dataset.kind === "link";
    dialog.querySelector("h2").textContent = dialog.dataset[!row ? "titleLink" : link ? "titleEditLink" : "titleEdit"];
    document.getElementById("file-dialog-button").textContent = dialog.dataset[row ? "btnEdit" : "btnNew"];
    nameInput.value = row ? row.dataset.name : "";
    urlInput.value = row ? row.dataset.url || "" : "";
    urlBox.hidden = !link;
    urlInput.required = link;
    areaBox.hidden = link;
    areaSelect.value = row ? row.dataset.cat : active;
    say(dialogError, "");
    dialog.showModal();
    (link && !row ? urlInput : nameInput).focus();
  }
  dialog.addEventListener("close", function () { form.reset(); AgentHub.clear(form); say(dialogError, ""); editing = null; });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var request;
    var next = !editing || editing.dataset.kind === "link" ? "links" : areaSelect.value;   // the tab to show afterwards
    if (!editing) {
      request = call("/projects/" + projectId + "/links", fields({ url: urlInput.value, name: nameInput.value }));
    } else {
      var values = { name: nameInput.value };
      if (editing.dataset.kind === "link") values.url = urlInput.value; else values.category = areaSelect.value;
      request = call("/files/" + editing.dataset.id, fields(values));
    }
    request.then(function () { show(next); dialog.close(); return refresh(); },
      function (problem) { say(dialogError, problem.message); });
  });

  // --- clicks on a row: the pencil changes name and area, the bin asks first; the name downloads a file (its link
  // says `?download=1`) and opens a link in a new tab; Markdown and text open in the big reader; the symbol and
  // the preview open the viewer of a picture, video or sound, and for anything else do what the name does.
  tile.addEventListener("click", function (event) {
    var button = event.target.closest("[data-file]");
    var row = event.target.closest(".file-row");
    if (button && row) {
      if (button.dataset.file === "edit") {
        openDialog(row);
      } else {
        if (tile.dataset.confirmDelete === "0") {          // the trash circle is red: no question
          call("/files/" + row.dataset.id + "/delete").then(refresh, refresh);
          return;
        }
        pendingId = row.dataset.id;
        confirmDialog.querySelector("h2").textContent = confirmDialog.dataset[row.dataset.kind === "link" ? "textLink" : "textFile"];
        confirmDialog.showModal();
      }
      return;
    }
    if (row && event.button === 0 && (event.shiftKey || event.ctrlKey || event.metaKey)) {   // marks only, nothing opens
      event.preventDefault();
      markRow(row, event);
      return;
    }
    var name = event.target.closest(".file-text");
    var picture = event.target.closest(".file-tile, .file-preview");
    if (!row || (!name && !picture)) return;
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;   // with a key held the browser decides
    var viewable = ["image", "video", "audio"].indexOf(row.dataset.kind) >= 0;
    if (row.dataset.editable === "1") { event.preventDefault(); openReader(row); }
    else if (picture && viewable) { event.preventDefault(); openViewer(row); }
    else if (picture && row.dataset.kind === "link") { window.open(row.dataset.url, "_blank", "noopener,noreferrer"); }
    else if (picture) { location.href = "/files/" + row.dataset.id + "?download=1"; }
  });

  // --- the viewer: a picture is shown, a video or sound gets a small player
  var viewer = document.getElementById("file-viewer");
  var viewerBody = document.getElementById("file-viewer-body");
  var viewerTitle = document.getElementById("file-viewer-title");
  var viewerId = null;
  var viewerPrev = document.getElementById("file-viewer-prev");
  var viewerNext = document.getElementById("file-viewer-next");
  function viewable(row) { return ["image", "video", "audio"].indexOf(row.dataset.kind) >= 0; }
  function neighbours() {      // the pictures, videos and sounds of the list that is showing, in the order shown
    return Array.prototype.filter.call(tile.querySelectorAll(".file-list:not([hidden]) .file-row"), viewable);
  }
  function showInViewer(row) {
    var kind = row.dataset.kind;
    var node = document.createElement(kind === "image" ? "img" : kind);
    if (kind === "image") node.alt = ""; else { node.controls = true; node.preload = "metadata"; node.playsInline = true; }
    node.src = "/files/" + row.dataset.id;
    viewerBody.textContent = "";
    viewerBody.appendChild(node);
    viewerTitle.textContent = row.dataset.name;
    viewerId = row.dataset.id;
    var all = neighbours();
    var at = all.map(function (r) { return r.dataset.id; }).indexOf(viewerId);
    viewerPrev.hidden = at <= 0;                             // no arrow where there is nothing further
    viewerNext.hidden = at < 0 || at >= all.length - 1;
  }
  function openViewer(row) { showInViewer(row); if (!viewer.open) viewer.showModal(); }
  function stepViewer(delta) {
    var all = neighbours();
    var next = all[all.map(function (r) { return r.dataset.id; }).indexOf(viewerId) + delta];
    if (next) showInViewer(next);
  }
  viewerPrev.addEventListener("click", function () { stepViewer(-1); });
  viewerNext.addEventListener("click", function () { stepViewer(1); });
  viewer.addEventListener("keydown", function (event) {
    if (event.key === "ArrowLeft") { event.preventDefault(); stepViewer(-1); }
    else if (event.key === "ArrowRight") { event.preventDefault(); stepViewer(1); }
  });
  var swipeFrom = null;        // a swipe over the picture goes to the next or the previous one
  viewerBody.addEventListener("pointerdown", function (event) { if (event.pointerType !== "mouse") swipeFrom = event.clientX; });
  viewerBody.addEventListener("pointerup", function (event) {
    if (swipeFrom !== null && Math.abs(event.clientX - swipeFrom) > 60) stepViewer(event.clientX < swipeFrom ? 1 : -1);
    swipeFrom = null;
  });
  viewer.addEventListener("close", function () { viewerBody.textContent = ""; viewerId = null; });   // stops the player
  document.getElementById("file-viewer-download").addEventListener("click", function () {
    if (viewerId) location.href = "/files/" + viewerId + "?download=1";
  });

  // --- the reader: Markdown and text over almost the whole window; its pencil switches to a plain editor
  var reader = document.getElementById("file-reader");
  var readerBody = document.getElementById("file-reader-body");
  var readerTitle = document.getElementById("file-reader-title");
  var readerText = document.getElementById("file-reader-text");
  var readerActions = document.getElementById("file-reader-actions");
  var readerError = document.getElementById("file-reader-error");
  var readerEdit = document.getElementById("file-reader-edit");
  var readerId = null;
  var readerName = "";
  var readerSource = "";
  var readerLoaded = false;

  // Inline marks of Markdown: **bold**, `code`, [text](link) and bare links; built from DOM nodes only, never from HTML.
  var INLINE = /\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)<>\]]+)|`([^`\n]+)`/g;
  function inline(target, text) {
    var last = 0;
    var m;
    INLINE.lastIndex = 0;
    while ((m = INLINE.exec(text))) {
      if (m.index > last) target.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        var strong = document.createElement("strong");
        strong.textContent = m[1];
        target.appendChild(strong);
      } else if (m[5] !== undefined) {
        var code = document.createElement("code");
        code.textContent = m[5];
        target.appendChild(code);
      } else {
        var link = document.createElement("a");
        link.href = m[3] || m[4];
        link.textContent = m[2] || m[4];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        target.appendChild(link);
      }
      last = INLINE.lastIndex;
    }
    if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
  }
  var BLOCK_START = /^(```|#{1,4}\s|\s*[-*+]\s+|\s*\d+[.)]\s+|>\s?|\s*([-*_])\2{2,}\s*$)/;
  function markdown(target, text) {
    var lines = text.replace(/\r\n?/g, "\n").split("\n");
    var i = 0;
    function add(tag, parent) { var node = document.createElement(tag); (parent || target).appendChild(node); return node; }
    while (i < lines.length) {
      var line = lines[i];
      var m;
      if (/^```/.test(line)) {
        var code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
        i++;
        add("code", add("pre")).textContent = code.join("\n");
      } else if ((m = /^(#{1,4})\s+(.*)$/.exec(line))) {
        inline(add("h" + m[1].length), m[2]);
        i++;
      } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
        add("hr");
        i++;
      } else if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        var ordered = /^\s*\d+[.)]\s+/.test(line);
        var list = add(ordered ? "ol" : "ul");
        var item = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        while (i < lines.length && item.test(lines[i])) { inline(add("li", list), lines[i].replace(item, "")); i++; }
      } else if (/^>\s?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
        inline(add("blockquote"), quote.join("\n"));
      } else if (!line.trim()) {
        i++;
      } else {
        var para = [];
        while (i < lines.length && lines[i].trim() && (para.length === 0 || !BLOCK_START.test(lines[i]))) para.push(lines[i++]);
        inline(add("p"), para.join("\n"));
      }
    }
  }

  function showReader() {
    readerBody.textContent = "";
    readerBody.classList.toggle("plain", !/\.md$/i.test(readerName));
    if (/\.md$/i.test(readerName)) markdown(readerBody, readerSource); else readerBody.textContent = readerSource;
  }
  function readerMode(edit) {
    readerBody.hidden = edit;
    readerText.hidden = !edit;
    readerActions.hidden = !edit;
    readerEdit.hidden = edit || !readerLoaded;
    if (edit) { readerText.value = readerSource; readerText.focus(); }
  }
  function openReader(row) {
    readerId = row.dataset.id;
    readerName = row.dataset.name;
    readerTitle.textContent = readerName;
    readerSource = "";
    readerLoaded = false;
    readerBody.textContent = "";
    say(readerError, "");
    readerMode(false);
    reader.showModal();
    call("/files/" + readerId + "/text", null, "GET").then(function (data) {
      readerSource = data.text;
      readerLoaded = true;
      showReader();
      readerMode(false);
    }, function (problem) { say(readerError, problem.message); });
  }
  readerEdit.addEventListener("click", function () { readerMode(true); });
  document.getElementById("file-reader-cancel").addEventListener("click", function () { say(readerError, ""); readerMode(false); });
  document.getElementById("file-reader-save").addEventListener("click", function () {
    var text = readerText.value;
    call("/files/" + readerId + "/text", fields({ text: text })).then(function () {
      readerSource = text;
      say(readerError, "");
      showReader();
      readerMode(false);
      refreshSoon();                       // the size changed
    }, function (problem) { say(readerError, problem.message); });
  });
  document.getElementById("file-reader-download").addEventListener("click", function () {
    if (readerId) location.href = "/files/" + readerId + "?download=1";
  });
  reader.addEventListener("close", function () { readerId = null; readerBody.textContent = ""; readerText.value = ""; });

  document.getElementById("file-confirm-yes").addEventListener("click", function () {
    var id = pendingId;
    var many = pendingMany;
    confirmDialog.close();
    if (many) deleteMarked(many);
    else if (id) call("/files/" + id + "/delete").then(refresh, refresh);
  });
  confirmDialog.addEventListener("close", function () { pendingId = null; pendingMany = null; });

  // --- the trash circle: pressed (glowing red) = deleting does not ask any more; the account remembers it
  var trashMode = document.getElementById("file-trash-mode");

  function markedIds() { return Object.keys(selected); }

  // --- the quiet download symbol left of the trash circle (Janis, 14.11.2026): it springs in while files are marked and
  // downloads them, one as itself, several as one ZIP. Works in every browser (dragging out only in Chrome and Edge).
  var downloadButton = document.getElementById("file-download");
  var downloadShown = false;
  var downloadSpring = Motion.spring(0, Motion.LIFT, function (p) {
    downloadButton.style.opacity = String(Math.max(0, Math.min(1, p)));
    downloadButton.style.transform = "scale(" + (0.6 + 0.4 * p) + ")";
    downloadButton.style.visibility = p < 0.01 ? "hidden" : "";
  }, 0.002);
  function markedFileIds() {
    return markedIds().filter(function (id) {
      var row = tile.querySelector('.file-row[data-id="' + id + '"]');
      return row && row.dataset.kind !== "link";
    });
  }
  function zipUrl(ids) { return "/projects/" + projectId + "/files/zip?ids=" + ids.join(","); }
  function renderDownload() {
    var count = markedFileIds().length;
    if (count) {
      var label = tile.dataset.downloadMarked.replace("{n}", count);
      downloadButton.setAttribute("aria-label", label);
      downloadButton.dataset.tip = label;
    }
    if (!!count === downloadShown) return;
    downloadShown = !!count;
    downloadButton.setAttribute("aria-hidden", downloadShown ? "false" : "true");
    downloadButton.tabIndex = downloadShown ? 0 : -1;
    downloadSpring.to(downloadShown ? 1 : 0);
  }
  downloadButton.style.visibility = "hidden";
  downloadButton.style.opacity = "0";
  downloadButton.addEventListener("click", function () {
    var ids = markedFileIds();
    if (!ids.length) return;
    location.assign(ids.length === 1 ? "/files/" + ids[0] + "?download=1" : zipUrl(ids));   // a download, the page stays
  });

  function renderTrashMode() {
    var asks = tile.dataset.confirmDelete !== "0";
    var marked = markedIds().length;
    trashMode.setAttribute("aria-pressed", asks ? "false" : "true");
    trashMode.classList.toggle("armed", !asks);
    trashMode.classList.toggle("bulk", marked > 0);               // marked files: the circle deletes them (green)
    var label = marked > 0 ? tile.dataset.deleteSelected.replace("{n}", marked) : trashMode.dataset.label;
    trashMode.setAttribute("aria-label", label);
    trashMode.dataset.tip = label;
    renderDownload();
    renderStatus();
  }
  trashMode.dataset.label = trashMode.getAttribute("aria-label");
  // Marking works as everywhere: a shift click marks everything from the row clicked last to this one (as the list shows
  // them), a ctrl click (cmd on a Mac) marks or unmarks only this row; ctrl and shift together add the range.
  function markRow(row, event) {
    var id = row.dataset.id;
    var more = event.ctrlKey || event.metaKey;
    if (event.shiftKey && anchorId && anchorId !== id) {
      var ids = Array.prototype.map.call(tile.querySelectorAll(".file-list:not([hidden]) .file-row"), function (r) { return r.dataset.id; });
      var from = ids.indexOf(anchorId);
      var to = ids.indexOf(id);
      if (from >= 0 && to >= 0) {
        if (!more) selected = {};
        for (var i = Math.min(from, to); i <= Math.max(from, to); i++) selected[ids[i]] = true;
        showMarks();
        return;                                                    // the anchor stays, the next range counts from it
      }
    }
    if (event.shiftKey) selected[id] = true;                       // a first shift click only marks
    else if (selected[id]) delete selected[id]; else selected[id] = true;
    anchorId = id;
    showMarks();
  }
  function showMarks() {                  // after the lists were swapped: the marks stay, vanished files lose theirs
    var present = {};
    Array.prototype.forEach.call(tile.querySelectorAll(".file-row"), function (row) {
      present[row.dataset.id] = true;
      row.classList.toggle("selected", !!selected[row.dataset.id]);
    });
    Object.keys(selected).forEach(function (id) { if (!present[id]) delete selected[id]; });
    renderTrashMode();
  }
  function deleteMarked(ids) {
    selected = {};
    anchorId = null;
    renderTrashMode();
    ids.reduce(function (chain, id) { return chain.then(function () { return call("/files/" + id + "/delete").catch(nothing); }); }, Promise.resolve())
      .then(refresh, refresh);
  }
  document.addEventListener("keydown", function (event) {      // Escape lets go of all marks
    if (event.key === "Escape" && markedIds().length && !document.querySelector("dialog[open]")) {
      selected = {};
      anchorId = null;
      showMarks();
    }
  });
  tile.addEventListener("mousedown", function (event) {        // a shift click must not select text
    if (event.shiftKey && event.target.closest(".file-row")) event.preventDefault();
  });
  renderTrashMode();
  trashMode.addEventListener("click", function () {
    var marked = markedIds();
    if (marked.length) {                                       // marked files: delete them, always asking once (also when the
      pendingMany = marked;                                    // switch says "do not ask": that is for single files)
      confirmDialog.querySelector("h2").textContent = confirmDialog.dataset.textMany.replace("{n}", marked.length);
      confirmDialog.showModal();
      return;
    }
    var asks = tile.dataset.confirmDelete !== "0";
    tile.dataset.confirmDelete = asks ? "0" : "1";
    renderTrashMode();
    flash(tile.dataset[asks ? "noteNoAsk" : "noteAsk"]);
    call("/files/preferences", fields({ confirm: asks ? "0" : "1" })).catch(nothing);
  });

  // --- the enlarge circle: the tile takes the whole Manager area, the other tiles step aside
  var expandButton = document.getElementById("file-expand");
  var managerView = document.getElementById("manager-view");
  var column = tile.closest(".mcol");
  function setExpanded(on, animate) {
    function apply() {
      managerView.classList.toggle("files-expanded", on);
      column.classList.add("has-files");
      expandButton.classList.toggle("on", on);
      expandButton.setAttribute("aria-pressed", on ? "true" : "false");
      var label = tile.dataset[on ? "collapse" : "expand"];
      expandButton.setAttribute("aria-label", label);
      expandButton.dataset.tip = label;
      store("files-expanded", on ? "1" : "0");
      placeThumb(true);
    }
    if (animate !== false && document.startViewTransition && !Motion.reduced()) {
      tile.style.viewTransitionName = "files-tile";             // this tile glides, the page around it blends
      tile.classList.add("vt-run");                             // no shadow and no edge light in the gliding picture
      var settled = function () { tile.style.viewTransitionName = ""; tile.classList.remove("vt-run"); placeThumb(true); };
      document.startViewTransition(apply).finished.then(settled, settled);
    } else {
      apply();
    }
  }
  expandButton.addEventListener("click", function () { setExpanded(!managerView.classList.contains("files-expanded")); });
  if (load("files-expanded") === "1") setExpanded(true, false);

  ensureThumbs();
})();
