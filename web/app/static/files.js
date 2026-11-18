// Files and links in the Manager view: five areas as tabs (a sliding highlight like an iOS segmented control),
// upload with requests sized to the line, several files at once under each other with a cross to cancel, drag files
// onto the tile (the tabs pop up and the one under the pointer takes the file) or paste them, drag a file out to the
// desktop or a folder (Chrome and Edge), the pencil renames and moves, a click opens a big reader for Markdown and text
// or a viewer for pictures, video and sound, delete after a confirmation. Needs core.js and motion.js.
//
// The upload itself is upload.js (pieces, resume, retries); its settings come from the administration page. Before an
// upload the server says which names already exist in the place; then a dialog asks: keep both, replace or skip.
//
// Folders (Janis, 18.11.2026): every list holds all rows of its area (folders first); this script shows the ones of
// the place chosen. Small tile: the folder bar under the tabs ("All" = every file of the area, then its top folders),
// sub-folders as rows, the path line with a back arrow. Enlarged tile: the explorer, a tree of areas and folders, the
// path bar and columns. Dropped folders keep their structure; marked rows dragged onto a folder, a segment, a tree
// entry or a tab move there.
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
  var folderBar = tile.querySelector(".file-folders");
  var folderThumb = folderBar.querySelector(".folder-thumb");
  var crumbsBox = tile.querySelector(".file-crumbs");
  var tree = tile.querySelector(".file-tree");
  var iconBox = document.getElementById("file-icons");
  var managerBox = document.getElementById("manager-view");
  var dialogMode = "edit";    // the pencil dialog: "edit", "link" (a new link) or "folder" (a new folder)
  var moving = null;          // ids of rows dragged inside the tile (to move them), or null

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
    }).then(function () {
      applyView(true);
      if (typeof showMarks === "function") showMarks();
      ensureThumbs();
      document.dispatchEvent(new CustomEvent("hub:trash-changed"));   // a deleted file is in the trash list now (mvault.js)
    }).catch(reload);
  }
  document.addEventListener("hub:files-changed", function () { refresh(); });   // restored from the trash (mvault.js)
  document.addEventListener("hub:files-notice", function (event) { flash(event.detail); });   // filetidy.js applied a plan
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
  // The big preview of a TIFF, HEIC or raw picture for the viewer (Janis, 14.11.2026): the whole picture, its long
  // side at most LARGE pixels, as a JPEG the server keeps next to the file. Made once, here in the browser.
  var LARGE = 2048;
  function drawLarge(element, width, height, turn) {
    if (!width || !height) return Promise.resolve(null);
    var scale = Math.min(1, LARGE / Math.max(width, height));
    var w = Math.round(width * scale), h = Math.round(height * scale), side = turn === 6 || turn === 8;
    var canvas = document.createElement("canvas");
    canvas.width = side ? h : w;
    canvas.height = side ? w : h;
    var context = canvas.getContext("2d");
    var angle = { 3: Math.PI, 6: Math.PI / 2, 8: -Math.PI / 2 }[turn];
    if (angle) { context.translate(canvas.width / 2, canvas.height / 2); context.rotate(angle); context.translate(-w / 2, -h / 2); }
    context.drawImage(element, 0, 0, width, height, 0, 0, w, h);
    return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.85); });
  }
  function thumbFromImage(src, turn, large) {
    return new Promise(function (resolve) {
      var image = new Image();
      image.onload = function () { resolve((large ? drawLarge : drawThumb)(image, image.naturalWidth, image.naturalHeight, turn)); };
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
  function photoFrom(buffer, type, large) {
    return window.HubTiff.preview(buffer, large).then(function (found) {
      if (found && found.blob) return withUrl(found.blob, function (url) { return thumbFromImage(url, found.turn, large); });
      if (found && found.image) {
        var canvas = document.createElement("canvas");
        canvas.width = found.image.width;
        canvas.height = found.image.height;
        canvas.getContext("2d").putImageData(found.image, 0, 0);
        return (large ? drawLarge : drawThumb)(canvas, canvas.width, canvas.height, found.turn);
      }
      return withUrl(new Blob([buffer], { type: type }), function (url) { return thumbFromImage(url, 1, large); });
    });
  }
  function photoType(name) { return PHOTO_TYPE[(name.split(".").pop() || "").toLowerCase()] || "application/octet-stream"; }
  // The big preview, from the file in hand (an upload) or fetched whole (an older file, the first time it is viewed).
  function largeFromPhoto(src, name, file) {
    var type = photoType(name);
    var load = file ? (file.size <= PHOTO_MAX ? file.arrayBuffer() : Promise.resolve(null))
      : fetch(src, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.arrayBuffer() : null; });
    return load.then(function (buffer) { return buffer ? photoFrom(buffer, type, true) : null; });
  }
  function sendPreview(id, blob) {
    return blob ? fetch("/files/" + id + "/preview", { method: "POST", body: blob }).then(function (r) { return r.ok; }, function () { return false; }) : Promise.resolve(false);
  }
  function thumbFromPhoto(src, name, file) {
    var type = photoType(name);
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
    if (PHOTO.test(job.file.name)) {   // the small preview, then the big one for the viewer
      return thumbFromPhoto(null, job.file.name, job.file).then(function (blob) { return sendThumb(job.id, blob); })
        .then(function () { return largeFromPhoto(null, job.file.name, job.file); })
        .then(function (blob) { return sendPreview(job.id, blob); });
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

  // --- folders: which place is open per area ("" = All in the small tile, the top of the area in the explorer)
  var place = {};
  try { place = JSON.parse(load("files-place") || "{}") || {}; } catch (e) { place = {}; }
  function expanded() { return !!managerBox && managerBox.classList.contains("files-expanded"); }
  function panelOf(cat) { return panels.filter(function (p) { return p.dataset.cat === cat; })[0]; }
  function rowsIn(cat) { return Array.prototype.slice.call(panelOf(cat).querySelectorAll(".file-row")); }
  function foldersIn(cat) {
    var map = {};
    rowsIn(cat).forEach(function (r) {
      if (r.dataset.folder === "1") map[r.dataset.id] = { id: r.dataset.id, name: r.dataset.name, parent: r.dataset.parent };
    });
    return map;
  }
  function chain(map, id) {            // the folders from the top of the area down to `id`
    var out = [], seen = {};
    while (id && map[id] && !seen[id]) { seen[id] = true; out.unshift(map[id]); id = map[id].parent; }
    return out;
  }
  function here() { var id = place[active] || ""; return id && foldersIn(active)[id] ? id : ""; }
  function areaName(cat) { return tabs.filter(function (t) { return t.dataset.cat === cat; })[0].dataset.name; }
  function iconOf(name) {
    var node = iconBox.content.querySelector('[data-icon="' + name + '"]');
    return node ? node.innerHTML : "";
  }
  function placeButton(cls, text, folder, svg) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    b.dataset.folder = folder;
    if (svg) b.innerHTML = svg;
    if (text) { var label = document.createElement("span"); label.textContent = text; b.appendChild(label); }
    return b;
  }
  var folderSegment = null;
  function folderSegments() { return Array.prototype.slice.call(folderBar.querySelectorAll(".file-folder")); }
  function buildBar(instant) {
    var top = chain(foldersIn(active), here())[0];
    var chosen = top ? top.id : "";
    var wanted = [{ id: "", name: tile.dataset.all }].concat(rowsIn(active).filter(function (r) {
      return r.dataset.folder === "1" && !r.dataset.parent;
    }).map(function (r) { return { id: r.dataset.id, name: r.dataset.name }; }));
    var old = folderSegments();
    var same = old.length === wanted.length && old.every(function (b, i) {
      return b.dataset.folder === wanted[i].id && b.textContent === wanted[i].name && b.dataset.cat === active;
    });
    if (!same) {                        // only rebuilt when the folders changed, so the glass can glide
      old.forEach(function (b) { b.remove(); });
      wanted.forEach(function (f) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "file-folder";
        b.setAttribute("role", "tab");
        b.dataset.seg = "";
        b.dataset.folder = f.id;
        b.dataset.cat = active;
        b.textContent = f.name;
        folderBar.appendChild(b);
      });
      instant = true;
    }
    folderSegments().forEach(function (b) { b.setAttribute("aria-selected", b.dataset.folder === chosen ? "true" : "false"); });
    fitBar(instant);
  }
  // Equal parts while every name fits; else each as wide as its name; else the bar scrolls (Janis, 13.11.2026).
  function fitBar(instant) {
    folderBar.classList.remove("by-name");
    var over = folderSegments().some(function (b) { return b.scrollWidth > b.clientWidth + 1; });
    folderBar.classList.toggle("by-name", over);
    if (folderSegment) folderSegment.place(instant !== false);
    var on = folderSegments().filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0];
    if (on && over) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  function buildCrumbs() {
    crumbsBox.textContent = "";
    var path = chain(foldersIn(active), here());
    var big = expanded();
    crumbsBox.hidden = !(big || path.length >= 2);
    if (crumbsBox.hidden) return;
    if (!big) {                         // the small tile: a back arrow to the folder above
      var back = placeButton("file-up-level", "", path[path.length - 2].id, iconOf("back"));
      back.setAttribute("aria-label", tile.dataset.back);
      back.dataset.tip = tile.dataset.back;
      back.dataset.label = path[path.length - 2].name;
      crumbsBox.appendChild(back);
    } else {
      var root = placeButton("", areaName(active), "", "");
      if (!path.length) root.setAttribute("aria-current", "location");
      crumbsBox.appendChild(root);
    }
    path.forEach(function (f, i) {
      var b = placeButton("", f.name, f.id, "");
      if (i === path.length - 1) b.setAttribute("aria-current", "location");
      crumbsBox.appendChild(b);
    });
    crumbsBox.scrollLeft = crumbsBox.scrollWidth;
  }
  function buildTree() {
    if (!expanded()) { tree.textContent = ""; return; }
    var list = document.createElement("ul");
    var open = here();
    tabs.forEach(function (tab) {
      var cat = tab.dataset.cat;
      var rows = rowsIn(cat).filter(function (r) { return r.dataset.folder === "1"; });
      var area = document.createElement("li");
      area.className = "tree-area";
      var head = placeButton("", tab.dataset.name, "", iconOf(cat));
      head.dataset.cat = cat;
      if (cat === active && !open) head.setAttribute("aria-current", "location");
      area.appendChild(head);
      var sub = document.createElement("ul");
      (function add(parent, depth) {
        if (depth > 24) return;
        rows.forEach(function (r) {
          if (r.dataset.parent !== parent) return;
          var item = document.createElement("li");
          var b = placeButton("tree-folder", r.dataset.name, r.dataset.id, iconOf("folder"));
          b.dataset.cat = cat;
          b.style.setProperty("--depth", depth);
          if (cat === active && open === r.dataset.id) b.setAttribute("aria-current", "location");
          item.appendChild(b);
          sub.appendChild(item);
          add(r.dataset.id, depth + 1);
        });
      })("", 1);
      area.appendChild(sub);
      list.appendChild(area);
    });
    tree.textContent = "";
    tree.appendChild(list);
  }
  // Shows the rows of the open place: under "All" (small tile, no folder open) every file of the area with its folder
  // named under it; otherwise what lies directly in the open folder (or at the top of the area), folders first.
  function applyView(instant) {
    var panel = panelOf(active);
    var current = here();
    var flat = !expanded() && !current;
    place[active] = current;
    store("files-place", JSON.stringify(place));
    var visible = 0;
    rowsIn(active).forEach(function (r) {
      var on = flat ? r.dataset.folder !== "1" : r.dataset.parent === current;
      r.hidden = !on;
      if (on) visible++;
    });
    panel.classList.toggle("all-mode", flat);
    var hint = panel.querySelector(".file-empty:not(.folder-empty)");
    var empty = panel.querySelector(".folder-empty");
    if (hint) hint.hidden = visible > 0 || !!current;
    if (!visible && current) {
      if (!empty) {
        empty = document.createElement("li");
        empty.className = "file-empty folder-empty muted";
        empty.textContent = tile.dataset.folderEmpty;
        panel.appendChild(empty);
      }
      empty.hidden = false;
    } else if (empty) {
      empty.hidden = true;
    }
    buildBar(instant);
    buildCrumbs();
    buildTree();
  }
  function choose(folder) {
    place[active] = folder || "";
    applyView(false);
    scroller.scrollTop = 0;
  }
  function spot() {                    // where the plus, pasting and a drop beside every target put files
    var folder = here();
    return folder ? { cat: active, folder: folder } : { cat: null, folder: "" };
  }
  folderSegment = Segment.attach(folderBar, {
    thumb: folderThumb,
    items: folderSegments,
    current: function () { return folderSegments().filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0]; },
    pick: function (b) { choose(b.dataset.folder); }
  });
  if (window.ResizeObserver) new ResizeObserver(function () { fitBar(true); }).observe(folderBar);

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
    applyView(true);
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

  function startJobs(list, category, taken, choice, folder) {
    var hits = taken.slice();
    var replaced = {};
    list.forEach(function (file) {
      var at = -1;
      for (var i = 0; i < hits.length && at < 0; i++) if (hits[i].name === file.name) at = i;
      if (at < 0) return uploader.add(file, { category: category, folder: folder });
      var hit = hits.splice(at, 1)[0];
      if (choice === "skip") return;
      var ids = hit.ids.filter(function (id) { return !replaced[id]; });
      if (choice === "replace" && ids.length) {
        ids.forEach(function (id) { replaced[id] = true; });
        return uploader.add(file, { category: category, folder: folder, replace: ids });
      }
      uploader.add(file, { category: category, folder: folder, name: hit.free });   // keep both (or a second copy)
    });
  }

  // `folder`: into that folder (its area is `category`); "" = the top of `category`, or by the ending without one.
  function addJobs(list, category, folder) {
    say(errorBox, "");
    if (category) show(category);
    var body = new FormData();
    list.forEach(function (file) { body.append("names", file.name); });
    if (category) body.append("category", category);
    if (folder) body.append("folder", folder);
    return call("/projects/" + projectId + "/files/check", body)
      .then(function (data) { return data.taken || []; }, function () { return []; })   // the check failing must not stop an upload
      .then(function (taken) {
        if (!taken.length) return startJobs(list, category, [], null, folder);
        return askSame(taken).then(function (choice) { startJobs(list, category, taken, choice, folder); });
      });
  }

  // A folder dropped from outside (Janis, 13.11.2026: they came as empty files): its tree is read in the browser, the
  // folders are made on the server one after the other (an existing one of the same name is joined), then the files
  // of each folder go up into it. Everything lands in the area of the place it was dropped on.
  function walk(entry, path, found) {
    if (entry.isFile) {
      return new Promise(function (resolve) {
        entry.file(function (file) { found.files.push({ file: file, path: path }); resolve(); }, function () { resolve(); });
      });
    }
    if (!entry.isDirectory) return Promise.resolve();
    var dir = path.concat([entry.name]);
    found.dirs.push(dir);
    var reader = entry.createReader();
    return new Promise(function (resolve) {
      var all = [];
      (function more() {                // readEntries gives at most 100 at a time
        reader.readEntries(function (batch) {
          if (!batch.length) { resolve(all); return; }
          all = all.concat(Array.prototype.slice.call(batch));
          more();
        }, function () { resolve(all); });
      })();
    }).then(function (children) {
      return children.reduce(function (done, child) { return done.then(function () { return walk(child, dir, found); }); }, Promise.resolve());
    });
  }
  function uploadTree(entries, where) {
    say(errorBox, "");
    var cat = where.cat && where.cat !== "links" ? where.cat : active !== "links" ? active : "documents";
    var found = { files: [], dirs: [] };
    var ids = { "": where.cat === cat ? where.folder || "" : "" };
    entries.reduce(function (done, entry) { return done.then(function () { return walk(entry, [], found); }); }, Promise.resolve())
      .then(function () {
        return found.dirs.reduce(function (done, dir) {
          return done.then(function () {
            return call("/projects/" + projectId + "/folders", fields({
              name: dir[dir.length - 1], category: cat, parent: ids[dir.slice(0, -1).join("/")] || "", reuse: "1"
            })).then(function (made) { ids[dir.join("/")] = String(made.id); });
          });
        }, Promise.resolve());
      })
      .then(function () {
        var groups = {};
        found.files.forEach(function (f) { var key = f.path.join("/"); (groups[key] = groups[key] || []).push(f.file); });
        return Object.keys(groups).reduce(function (done, key) {
          return done.then(function () { return ids[key] !== undefined ? addJobs(groups[key], cat, ids[key]) : null; });
        }, Promise.resolve());
      })
      .then(refreshSoon, function (problem) { say(errorBox, problem.message); refreshSoon(); });
  }

  function moveRows(ids, target) {
    call("/projects/" + projectId + "/files/move", fields({ ids: ids.join(","), category: target.cat, folder: target.folder || "" }))
      .then(function (answer) {
        selected = {};
        anchorId = null;
        flash(tile.dataset.moved.replace("{n}", answer.moved));
        return refresh();
      }, function (problem) { say(errorBox, problem.message); });
  }

  addButton.addEventListener("click", function () {
    if (active === "links") openDialog(null, "link"); else picker.click();
  });
  document.getElementById("file-folder-add").addEventListener("click", function () { openDialog(null, "folder"); });
  picker.addEventListener("change", function () {
    var list = Array.prototype.slice.call(picker.files);
    var where = spot();
    picker.value = "";
    if (list.length) addJobs(list, where.cat, where.folder);
  });

  // Files pasted with Ctrl+V or Cmd+V (not while writing in a field, and only while this view is showing).
  document.addEventListener("paste", function (event) {
    var target = event.target;
    var typing = target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
    var list = event.clipboardData ? Array.prototype.slice.call(event.clipboardData.files) : [];
    if (typing || !list.length || !tile.offsetParent) return;
    event.preventDefault();
    var where = spot();
    addJobs(list, where.cat, where.folder);
  });

  // --- drag files onto the tile: the tabs pop up like glass drops, the one under the pointer pops more
  function pop(tab, scale) {
    if (!tab.__pop) tab.__pop = Motion.spring(1, Motion.LIFT, function (v) { tab.style.transform = "scale(" + v + ")"; }, 0.002);
    tab.__pop.to(scale);
  }
  var hot = null;                      // the place under the pointer: { node, cat, folder, name }
  var dragging = false;
  function hasFiles(event) { return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") >= 0; }
  // Places that take a drop: a tab (the top of its area), a segment of the folder bar, a folder row, an entry of the
  // tree and a step of the path.
  var PLACES = ".file-tab, .file-folder, .file-row.folder, .file-tree button, .file-crumbs button";
  function targetOf(element) {
    var node = element && element.closest ? element.closest(PLACES) : null;
    if (!node || !tile.contains(node)) return null;
    if (node.classList.contains("file-tab")) return { node: node, cat: node.dataset.cat, folder: "", name: node.dataset.name };
    if (node.classList.contains("file-row")) return { node: node, cat: node.dataset.cat, folder: node.dataset.id, name: node.dataset.name };
    var cat = node.dataset.cat || active;
    var name = node.dataset.label || node.textContent || areaName(cat);
    if (node.classList.contains("file-folder") && !node.dataset.folder) name = areaName(cat);
    return { node: node, cat: cat, folder: node.dataset.folder || "", name: name };
  }
  function canMove(target) {           // never a folder into itself
    return !!target && moving.indexOf(target.folder) < 0;
  }
  function setHot(target) {
    var node = target ? target.node : null;
    if (dragging && (hot ? hot.node : null) === node && node) return;
    hot = target;
    dragText = target ? tile.dataset[moving ? "moveTo" : "dropTo"].replace("{name}", target.name) : moving ? "" : dropText;
    renderStatus();
    Array.prototype.forEach.call(tile.querySelectorAll(".hot"), function (el) { if (el !== node) el.classList.remove("hot"); });
    if (node) node.classList.add("hot");
    tabs.forEach(function (other) { pop(other, !dragging ? 1 : other === node ? 1.16 : 1.06); });
  }
  function endDrag() {
    dragging = false;
    tile.classList.remove("dropping");
    hot = null;
    dragText = "";
    renderStatus();
    Array.prototype.forEach.call(tile.querySelectorAll(".hot"), function (el) { el.classList.remove("hot"); });
    tabs.forEach(function (tab) { pop(tab, 1); });
  }
  tile.addEventListener("dragover", function (event) {
    if (!hasFiles(event) && !moving) return;
    var target = targetOf(event.target);
    if (moving && !canMove(target)) target = null;
    dragging = true;
    tile.classList.add("dropping");
    if (moving && !target) { setHot(null); return; }      // rows only drop on a place
    event.preventDefault();
    event.dataTransfer.dropEffect = moving ? "move" : "copy";
    setHot(target);
  });
  tile.addEventListener("dragleave", function (event) {
    if (!tile.contains(event.relatedTarget)) endDrag();
  });
  tile.addEventListener("drop", function (event) {
    if (moving) {
      event.preventDefault();
      var into = hot;
      var ids = moving;
      endDrag();
      if (into) moveRows(ids, into);
      return;
    }
    if (!hasFiles(event)) return;
    event.preventDefault();
    var items = event.dataTransfer.items ? Array.prototype.slice.call(event.dataTransfer.items) : [];
    var entries = items.map(function (item) { return item.webkitGetAsEntry ? item.webkitGetAsEntry() : null; }).filter(Boolean);
    var list = Array.prototype.slice.call(event.dataTransfer.files);
    var where = hot ? { cat: hot.cat, folder: hot.folder } : spot();
    endDrag();
    if (entries.some(function (entry) { return entry.isDirectory; })) uploadTree(entries, where);
    else if (list.length) addJobs(list, where.cat, where.folder);
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
  tile.addEventListener("dragend", function () { moving = null; endDrag(); release(); });

  tile.addEventListener("dragstart", function (event) {
    var row = event.target.closest ? event.target.closest(".file-row") : null;
    if (!row) return;
    var rows = row.classList.contains("selected") ? Array.prototype.slice.call(tile.querySelectorAll(".file-row.selected")) : [row];
    moving = rows.map(function (r) { return r.dataset.id; });   // dropped on a place in the tile, they move there
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
    } else if (fileRows.length === 1 && fileRows[0].dataset.folder === "1") {   // a folder comes as its ZIP
      event.dataTransfer.setData("DownloadURL", "application/zip:" + fileRows[0].dataset.name + ".zip:" + location.origin +
                                 zipUrl([fileRows[0].dataset.id]));
    } else if (fileRows.length === 1) {
      event.dataTransfer.setData("DownloadURL", "application/octet-stream:" + fileRows[0].dataset.name + ":" +
                                 location.origin + "/files/" + fileRows[0].dataset.id);
    } else {
      var urls = rows.map(function (r) { return r.dataset.url; }).join("\r\n");
      event.dataTransfer.setData("text/uri-list", urls);
      event.dataTransfer.setData("text/plain", urls);
    }
    event.dataTransfer.effectAllowed = "copyMove";
  });

  // --- the pencil dialog: a new link, or rename and move (the content is read and edited in the reader)
  function openDialog(row, mode) {
    editing = row;
    dialogMode = row ? "edit" : mode || "link";
    var folder = dialogMode === "folder" || (!!row && row.dataset.folder === "1");
    var link = !folder && (!row || row.dataset.kind === "link");
    dialog.querySelector("h2").textContent = dialog.dataset[!row ? (folder ? "titleFolder" : "titleLink")
      : folder ? "titleEditFolder" : link ? "titleEditLink" : "titleEdit"];
    document.getElementById("file-dialog-button").textContent = dialog.dataset[row ? "btnEdit" : "btnNew"];
    nameInput.value = row ? row.dataset.name : "";
    urlInput.value = row ? row.dataset.url || "" : "";
    urlBox.hidden = !link;
    urlInput.required = link;
    areaBox.hidden = link || !row || row.dataset.cat === "links";   // a new folder is made where you are
    areaSelect.value = row ? row.dataset.cat : active;
    say(dialogError, "");
    dialog.showModal();
    (link && !row ? urlInput : nameInput).focus();
  }
  function isFolder(row) { return !!row && row.dataset.folder === "1"; }
  dialog.addEventListener("close", function () { form.reset(); AgentHub.clear(form); say(dialogError, ""); editing = null; });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var request;
    var next = !editing ? (dialogMode === "folder" ? active : "links")      // the tab to show afterwards
      : editing.dataset.kind === "link" || editing.dataset.cat === "links" ? "links" : areaSelect.value;
    if (!editing && dialogMode === "folder") {
      request = call("/projects/" + projectId + "/folders", fields({ name: nameInput.value, category: active, parent: here() }));
    } else if (!editing) {
      request = call("/projects/" + projectId + "/links", fields({ url: urlInput.value, name: nameInput.value }));
    } else {
      var values = { name: nameInput.value };
      if (editing.dataset.kind === "link") values.url = urlInput.value;
      else if (editing.dataset.cat !== "links") values.category = areaSelect.value;
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
        if (tile.dataset.confirmDelete === "0" && !isFolder(row)) {   // the trash circle is red: no question (a folder asks)
          call("/files/" + row.dataset.id + "/delete").then(refresh, refresh);
          return;
        }
        pendingId = row.dataset.id;
        confirmDialog.querySelector("h2").textContent = confirmDialog.dataset[isFolder(row) ? "textFolder"
          : row.dataset.kind === "link" ? "textLink" : "textFile"];
        confirmDialog.showModal();
      }
      return;
    }
    var step = event.target.closest(".file-crumbs button, .file-folder");
    if (step) { choose(step.dataset.folder); return; }
    var entry = event.target.closest(".file-tree button");
    if (entry) { if (entry.dataset.cat !== active) show(entry.dataset.cat); choose(entry.dataset.folder); return; }
    if (row && event.button === 0 && (event.shiftKey || event.ctrlKey || event.metaKey)) {   // marks only, nothing opens
      event.preventDefault();
      markRow(row, event);
      return;
    }
    var name = event.target.closest(".file-text");
    var picture = event.target.closest(".file-tile, .file-preview");
    if (!row || (!name && !picture)) return;
    if (isFolder(row)) { event.preventDefault(); choose(row.dataset.id); return; }       // a folder opens
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;   // with a key held the browser decides
    var viewable = ["image", "photo", "video", "audio"].indexOf(row.dataset.kind) >= 0;
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
  function viewable(row) { return ["image", "photo", "video", "audio"].indexOf(row.dataset.kind) >= 0; }
  function neighbours() {      // the pictures, videos and sounds of the list that is showing, in the order shown
    return Array.prototype.filter.call(tile.querySelectorAll(".file-list:not([hidden]) .file-row:not([hidden])"), viewable);
  }
  function showInViewer(row) {
    var kind = row.dataset.kind;
    var picture = kind === "image" || kind === "photo";
    var node = document.createElement(picture ? "img" : kind);
    if (picture) node.alt = ""; else { node.controls = true; node.preload = "metadata"; node.playsInline = true; }
    if (kind === "photo") {
      // TIFF, HEIC, raw: the big preview the server keeps; without one yet it is made now, once (the file is fetched
      // whole), shown and kept for the next time. The spinner dots show meanwhile.
      var id = row.dataset.id;
      node.src = "/files/" + id + "/preview";
      node.onerror = function () {
        node.onerror = null;
        node.removeAttribute("src");
        var waiting = document.createElement("span");
        waiting.className = "loading-dots viewer-wait";
        for (var d = 0; d < 3; d++) waiting.appendChild(document.createElement("i"));
        viewerBody.appendChild(waiting);
        largeFromPhoto("/files/" + id, row.dataset.name).then(function (blob) {
          waiting.remove();
          if (!blob || viewerId !== id) return;
          node.src = URL.createObjectURL(blob);
          sendPreview(id, blob);
        });
      };
    } else {
      node.src = "/files/" + row.dataset.id;
    }
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
    tile.style.setProperty("--dl", Math.max(0, Math.min(1, p)).toFixed(3));   // the area name fades under it
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
    var one = ids.length === 1 && !isFolder(tile.querySelector('.file-row[data-id="' + ids[0] + '"]'));
    location.assign(one ? "/files/" + ids[0] + "?download=1" : zipUrl(ids));   // a download, the page stays
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
      var ids = Array.prototype.map.call(tile.querySelectorAll(".file-list:not([hidden]) .file-row:not([hidden])"), function (r) { return r.dataset.id; });
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
      applyView(true);
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
