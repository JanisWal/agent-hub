// Structure the folders automatically (Janis, 18.11.2026; web/app/autofolders.py): the circle in the enlarged file
// tile opens a dialog with the switch "Include contents". "Get a proposal" asks the AI; while it works the dialog shows
// three dots and asks the server every two seconds. Then it shows the new tree (moved rows and new folders marked)
// with "Apply"; nothing moves before that. Closing the dialog keeps a job on its way; opening it again shows where it
// stands. After "Apply" the file tile swaps its lists (files.js, event hub:files-changed). Needs core.js.
(function () {
  var dialog = document.getElementById("file-tidy-dialog");
  var openButton = document.getElementById("file-tidy");
  var project = document.querySelector(".project");
  if (!dialog || !openButton || !project) return;
  var base = "/projects/" + project.dataset.id + "/files/structure";
  var text = dialog.dataset;
  var contents = document.getElementById("file-tidy-contents");
  var steps = Array.prototype.slice.call(dialog.querySelectorAll("[data-step]"));
  var note = document.getElementById("file-tidy-note");
  var summary = document.getElementById("file-tidy-summary");
  var tree = document.getElementById("file-tidy-tree");
  var errorBox = document.getElementById("file-tidy-error");
  var goButton = document.getElementById("file-tidy-go");
  var cancelButton = document.getElementById("file-tidy-cancel");
  var iconBox = document.getElementById("file-icons");
  var state = "none";
  var pollTimer = null;
  var busy = false;

  function say(message) { errorBox.textContent = message || ""; errorBox.hidden = !message; }
  function show(step) { steps.forEach(function (el) { el.hidden = el.dataset.step !== step; }); }
  function icon(name) {
    var source = iconBox && iconBox.querySelector('[data-icon="' + name + '"] svg');
    return source ? source.cloneNode(true) : document.createElement("span");
  }
  function call(url, body) {
    return fetch(url, { method: body ? "POST" : "GET", body: body, credentials: "same-origin" }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || !data.ok) throw new Error(data.message || text.errNet);
        return data;
      });
    }, function () { throw new Error(text.errNet); });
  }

  function failureText(kind) { return kind === "auth" ? text.failAuth : kind === "limit" ? text.failLimit : text.failed; }

  function drawTree(nodes) {
    tree.textContent = "";
    nodes.forEach(function (n) {
      var row = document.createElement("li");
      row.className = "tidy-row" + (n.kind === "area" ? " tidy-area" : n.kind === "folder" ? " tidy-folder" : "") +
        (n.moved || n.new ? " changed" : "");
      row.style.setProperty("--depth", n.depth);
      row.appendChild(icon(n.kind === "area" || n.kind !== "folder" ? n.area : "folder"));
      var name = document.createElement("span");
      name.className = "tidy-name";
      name.textContent = n.kind === "area" ? (text["area" + n.area.charAt(0).toUpperCase() + n.area.slice(1)] || n.name) : n.name;
      row.appendChild(name);
      if (n.new || n.moved) {
        var tag = document.createElement("small");
        tag.className = "tidy-tag";
        tag.textContent = n.new ? text.newTag : text.movedTag;
        row.appendChild(tag);
      }
      tree.appendChild(row);
    });
  }

  // One look at the server: none (start), queued/running (dots, look again soon), done (the tree), failed (start + why)
  function render(data) {
    state = data.status;
    clearTimeout(pollTimer);
    goButton.hidden = false;
    goButton.disabled = false;
    cancelButton.textContent = text.cancel;
    if (state === "queued" || state === "running") {
      show("working");
      goButton.hidden = true;
      cancelButton.textContent = text.close;
      contents.checked = !!data.contents;
      pollTimer = setTimeout(look, 2000);
    } else if (state === "done") {
      show("plan");
      note.textContent = data.note || "";
      note.hidden = !data.note;
      summary.textContent = data.moved ? text.summary.replace("{moved}", data.moved).replace("{folders}", data.folders) : text.nothing;
      drawTree(data.moved ? data.nodes : []);
      goButton.textContent = text.apply;
      goButton.hidden = !data.moved;
      cancelButton.textContent = text.discard;
    } else {
      show("start");
      goButton.textContent = text.start;
      say(state === "failed" ? failureText(data.failure) : "");
    }
  }
  function look() {
    if (!dialog.open) return;
    call(base).then(render, function (problem) { say(problem.message); pollTimer = setTimeout(look, 4000); });
  }

  openButton.addEventListener("click", function () {
    say("");
    show(state === "done" ? "plan" : state === "none" || state === "failed" ? "start" : "working");
    if (!dialog.open) dialog.showModal();
    look();
  });
  dialog.addEventListener("close", function () { clearTimeout(pollTimer); });

  goButton.addEventListener("click", function () {
    if (busy) return;
    busy = true;
    goButton.disabled = true;
    say("");
    var body = new FormData();
    if (state === "done") {
      call(base + "/apply", body).then(function (data) {
        state = "none";
        dialog.close();
        document.dispatchEvent(new CustomEvent("hub:files-changed"));
        document.dispatchEvent(new CustomEvent("hub:files-notice", { detail: text.done.replace("{n}", data.moved) }));
      }, function (problem) { say(problem.message); }).then(function () { busy = false; goButton.disabled = false; });
      return;
    }
    body.append("contents", contents.checked ? "1" : "0");
    call(base, body).then(function () {
      render({ status: "queued", contents: contents.checked });
    }, function (problem) { say(problem.message); goButton.disabled = false; }).then(function () { busy = false; });
  });

  cancelButton.addEventListener("click", function () {
    if (state === "done") {   // "Discard": the plan goes, nothing was moved
      call(base + "/discard", new FormData()).catch(function () {});
      state = "none";
    }
    dialog.close();
  });
})();
