// Loaded on every logged-in page: the dialogs of the AIs that connect with an API key (ui.KEY_DIALOG, ai_link.py,
// Mistral). The server renders all texts; this script shows one step at a time. Paste the key -> the runner checks it
// with the provider (GET /ai/<provider>/status tells how it went). The key leaves the page once and is not kept here.
(function () {
  // "Make standard" (Janis, 15.11.2026): the row glides to the top (Motion.flip), then the page comes again quietly,
  // because the model picker shows only the standard AI's models.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-ai-default]");
    if (!button) return;
    button.disabled = true;
    var body = new FormData();
    body.append("provider", button.dataset.aiDefault);
    fetch("/ai/default", { method: "POST", body: body }).then(function (r) {
      if (!r.ok) throw new Error("default");
      var row = button.closest("[data-ai]");
      var first = document.querySelector("#settings .service[data-ai]");
      var rows = Array.prototype.slice.call(document.querySelectorAll("#settings .service"));
      var move = function () { if (row && first && row !== first) first.parentNode.insertBefore(row, first); };
      if (window.Motion && !window.Motion.reduced()) window.Motion.flip(rows, move, row); else move();
      setTimeout(function () { window.AgentHub.reload(); }, 450);
    }).catch(function () { button.disabled = false; });
  });

  var CHECK_FOR = 150000; // ms: the hub gives up a check after two minutes (ai_link.CHECK_SECONDS)

  function post(url, body) {
    return fetch(url, { method: "POST", body: body || null })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.httpStatus = r.status; return d; }); })
      .catch(function () { return { ok: false }; });
  }

  document.querySelectorAll("dialog[data-provider]").forEach(function (dialog) {
    var provider = dialog.dataset.provider;
    var button = document.querySelector('[data-key-open="' + provider + '"]');
    if (!button || typeof dialog.showModal !== "function") return;
    var steps = {};
    dialog.querySelectorAll("[data-step]").forEach(function (el) { steps[el.dataset.step] = el; });
    var form = steps.key;
    var timer = null;
    var since = 0;

    function show(name) {
      Object.keys(steps).forEach(function (key) { steps[key].hidden = key !== name; });
    }

    function stop() { clearTimeout(timer); timer = null; }

    function poll() {
      fetch("/ai/" + provider + "/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!dialog.open || !data.ok) return;
          if (data.status === "connected") { stop(); show("done"); return; }
          if (data.status !== "connecting" || Date.now() - since > CHECK_FOR) { stop(); show("failed"); return; }
          timer = setTimeout(poll, 1500);
        })
        .catch(function () { if (dialog.open) timer = setTimeout(poll, 3000); });
    }

    button.addEventListener("click", function () {
      stop();
      form.reset();
      show(button.dataset.status === "connected" ? "disconnect" : "key");
      dialog.showModal();
      var field = form.querySelector("input");
      if (!form.hidden && field) field.focus();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!window.AgentHub.validate(form)) return;
      var body = new FormData(form);
      form.reset();   // the key does not stay in the page
      show("check");
      post("/ai/" + provider + "/connect", body).then(function (data) {
        if (!data.ok && data.httpStatus !== 409) { show("failed"); return; }   // 409: an earlier key is being checked
        since = Date.now();
        poll();
      });
    });

    dialog.addEventListener("click", function (event) {
      var target = event.target.closest("button");
      if (!target) return;
      if (target.hasAttribute("data-finish")) { dialog.close(); window.AgentHub.reload(); }
      else if (target.hasAttribute("data-disconnect")) {
        post("/ai/" + provider + "/disconnect").then(function () { dialog.close(); window.AgentHub.reload(); });
      }
    });

    dialog.addEventListener("close", stop);
  });
})();
