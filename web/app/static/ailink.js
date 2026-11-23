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
      // Then the rows as the server draws them now (arrow, stars), without a reload: the drawer and the open list
      // stay (Janis, 21.11.2026). A model picker on the page takes the value the new standard gives it.
      var wasOpen = !document.getElementById("ai-more").hidden;
      setTimeout(function () {
        window.AgentHub.swap(["ai-services"]).then(function (fresh) {
          var more = document.getElementById("ai-more"), arrow = document.getElementById("ai-toggle");
          if (wasOpen && more && arrow) { more.hidden = false; arrow.setAttribute("aria-expanded", "true"); }
          if (window.AgentHub.equalizeTiles) window.AgentHub.equalizeTiles();
          if (window.AgentHub.refreshPickers) window.AgentHub.refreshPickers(fresh);
        }).catch(function () { window.AgentHub.reload(); });
      }, 450);
    }).catch(function () { button.disabled = false; });
  });

  // What an AI used (ui._usage_dialog): the button of its row opens the window with its block and, below, all AIs.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-usage]");
    var dialog = document.getElementById("usage-dialog");
    if (!button || !dialog || typeof dialog.showModal !== "function") return;
    dialog.querySelectorAll("[data-usage-for]").forEach(function (block) {
      block.hidden = block.dataset.usageFor !== button.dataset.usage && block.dataset.usageFor !== "all";
    });
    dialog.showModal();
  });

  var CHECK_FOR = 150000; // ms: the hub gives up a check after two minutes (ai_link.CHECK_SECONDS)
  var SIGN_IN_FOR = 990000; // ms: a sign-in with a one-time code may take 15 minutes (ai_link.DEVICE_SECONDS)

  function post(url, body) {
    return fetch(url, { method: "POST", body: body || null })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.httpStatus = r.status; return d; }); })
      .catch(function () { return { ok: false }; });
  }

  document.querySelectorAll("dialog[data-provider]").forEach(function (dialog) {
    var kind = dialog.dataset.provider;
    // The further AIs share one dialog: the open tile ("custom") and each connected one ("custom-3", ui._key_row).
    var selector = '[data-key-open="' + kind + '"], [data-manage="' + kind + '"]' +
                   (kind === "custom" ? ', [data-key-open^="custom-"]' : "");
    if (typeof dialog.showModal !== "function") return;
    var provider = kind;   // the connection the dialog is about now
    var fieldError = dialog.querySelector("[data-field-error]");
    var changed = false;   // a half was disconnected in the dialog: the page comes again when it closes
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
          // ChatGPT: the server shows the link and the one-time code of the sign-in at OpenAI (ui.DEVICE_DIALOG)
          if (data.url && data.code && steps.device) {
            var link = dialog.querySelector("[data-device-link]");
            link.href = data.url;
            dialog.querySelector("[data-device-code]").textContent = data.code;
            if (steps.device.hidden) show("device");
          }
          var limit = steps.device ? SIGN_IN_FOR : CHECK_FOR;
          if (data.status !== "connecting" || Date.now() - since > limit) { stop(); show("failed"); return; }
          timer = setTimeout(poll, 1500);
        })
        .catch(function () { if (dialog.open) timer = setTimeout(poll, 3000); });
    }

    // On the document: the drawer's rows can be swapped ("use as standard" above).
    document.addEventListener("click", function (event) {
      var button = event.target.closest(selector);
      if (!button) return;
      stop();
      changed = false;
      provider = button.dataset.keyOpen || button.dataset.manage;
      form.reset();
      if (fieldError) fieldError.hidden = true;
      var name = form.querySelector('input[name="label"]');
      if (name && button.dataset.label) name.value = button.dataset.label;
      // A ready-made AI (ui.PRESETS): its address is filled in and the page for its key is offered
      var address = form.querySelector('input[name="endpoint"]');
      if (address && button.dataset.endpoint) address.value = button.dataset.endpoint;
      var page = dialog.querySelector("[data-key-page]");
      if (page) {
        var known = /^https:\/\//.test(button.dataset.keyPage || "");
        page.hidden = !known;
        if (known) page.href = button.dataset.keyPage;
      }
      // "Connected" of an AI with a plan and a key (ui._status): both halves as they are
      if (button.dataset.manage) show(button.dataset.plan === "connected" ? "plan-on" : "key");
      else show(button.dataset.status === "connected" ? "disconnect" : "key");
      // A refused or expired connection can be renewed or disconnected from the same dialog (Janis, 23.11.2026)
      var out = dialog.querySelector("[data-to-disconnect]");
      if (out) out.hidden = !(button.dataset.status === "expired" || button.dataset.status === "noplan");
      dialog.showModal();
      var field = form.querySelector("input");
      if (!form.hidden && field) field.focus();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!window.AgentHub.validate(form)) return;
      var body = new FormData(form);
      var key = form.querySelector('input[name="key"]');
      if (key) key.value = "";   // the key does not stay in the page
      show("check");
      post("/ai/" + provider + "/connect", body).then(function (data) {
        // a further AI: the server says which field does not fit; the other fields stay for a correction
        if (fieldError && data.field && fieldError.dataset[data.field]) {
          fieldError.textContent = fieldError.dataset[data.field];
          fieldError.hidden = false;
          show("key");
          return;
        }
        if (!data.ok && data.httpStatus !== 409) { show("failed"); return; }   // 409: an earlier key is being checked
        if (data.provider) provider = data.provider;   // "custom" took the next free place
        form.reset();
        since = Date.now();
        poll();
      });
    });

    dialog.addEventListener("click", function (event) {
      var target = event.target.closest("button");
      if (!target) return;
      if (target.hasAttribute("data-finish")) { dialog.close(); window.AgentHub.reload(); }
      else if (target.hasAttribute("data-to-disconnect")) show("disconnect");
      else if (target.hasAttribute("data-disconnect")) {   // with an API key half: the plan and the key
        var both = dialog.querySelector("[data-api]");
        post("/ai/" + provider + "/disconnect")
          .then(function () { return both ? post("/ai/" + provider + "/api/remove") : null; })
          .then(function () { dialog.close(); window.AgentHub.reload(); });
      }
      else if (target.hasAttribute("data-plan-off")) {     // only the plan; the key stays
        target.disabled = true;
        post("/ai/" + provider + "/disconnect").then(function () { target.disabled = false; changed = true; show("key"); });
      }
    });

    dialog.addEventListener("close", function () {
      stop();
      if (changed || dialog.dataset.apiChanged) { delete dialog.dataset.apiChanged; window.AgentHub.reload(); }
    });
  });
})();
