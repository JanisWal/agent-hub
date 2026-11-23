// Loaded on every logged-in page: the dialog that connects (or disconnects) the user's Claude.
// The server renders all texts as steps inside #claude-dialog; this script only shows one step at a
// time and asks the server how the login is going (GET /claude/status). The login itself runs in
// the runner: link -> the user signs in at Claude -> he types the code here.
(function () {
  // Delete the chat history: an own button in the menu, a red "are you sure" dialog, then it is gone.
  var clearOpen = document.getElementById("chat-clear-open");
  var clearDialog = document.getElementById("chat-clear-dialog");
  var clearYes = document.getElementById("chat-clear-yes");
  if (clearOpen && clearDialog && clearYes && typeof clearDialog.showModal === "function") {
    clearOpen.addEventListener("click", function () { clearDialog.showModal(); });
    clearYes.addEventListener("click", function () {
      clearYes.disabled = true;
      fetch("/chat/delete", { method: "POST" })
        .catch(function () {})
        .then(function () { clearYes.disabled = false; clearDialog.close(); window.AgentHub.reload(); });
    });
  }

  var dialog = document.getElementById("claude-dialog");
  // The manager chat found the sign-in lost (chat.js): the row says "expired" and its link "renew", as after a page load.
  // The row is looked up each time: the drawer's rows can be swapped (ailink.js).
  window.AgentHub = window.AgentHub || {};
  window.AgentHub.claudeExpired = function () {
    var row = document.getElementById("claude-row");
    var openButton = document.getElementById("claude-open");
    if (!row || !openButton || openButton.dataset.status === "expired") return;
    row.className = "setting service expired";
    openButton.textContent = row.dataset.expired;   // the status is the button
    openButton.dataset.status = "expired";
  };
  if (!dialog || typeof dialog.showModal !== "function") return;

  var STUCK_AFTER = 45000; // ms without a link from the runner
  var steps = {};
  dialog.querySelectorAll("[data-step]").forEach(function (el) { steps[el.dataset.step] = el; });
  var link = document.getElementById("claude-link");
  var form = steps.link;
  var timer = null;
  var current = "";
  var started = false;   // we began a login in this dialog
  var finished = false;  // it ended (connected, failed or disconnected): nothing to cancel
  var submitted = false; // the code was sent
  var since = 0;
  var changed = false;   // a half was disconnected in the dialog: the page comes again when it closes

  function show(name) {
    current = name;
    Object.keys(steps).forEach(function (key) { steps[key].hidden = key !== name; });
  }

  function post(url, body) {
    return fetch(url, { method: "POST", body: body || null })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d.httpStatus = r.status; return d; }); })
      .catch(function () { return { ok: false }; });
  }

  function stop() { clearTimeout(timer); timer = null; }

  // "stuck" leaves the login open on purpose: closing the dialog then cancels it.
  function end(name) { finished = name !== "stuck"; stop(); show(name); }

  function poll() {
    fetch("/claude/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!dialog.open || finished || !data.ok) return;
        if (data.status === "connected") return end("done");
        if (data.status === "connecting") {
          if (submitted) { if (current !== "check") show("check"); }
          else if (data.login_url) {
            if (current !== "link") {
              link.href = data.login_url;
              show("link");
              var field = form.querySelector("input");
              if (field) field.focus();
            }
          } else if (Date.now() - since > STUCK_AFTER) {
            return end("stuck");
          }
        } else if (started) {
          return end("failed"); // the login ended without success (or was never started)
        }
      })
      .catch(function () {})
      .then(function () { if (dialog.open && !finished) timer = setTimeout(poll, 1500); });
  }

  function reset() { started = finished = submitted = changed = false; current = ""; stop(); }

  // "Connected" (ui._status, Janis 21.11.2026): the dialog with both halves as they are; each can go on its own.
  // On the document: the drawer's rows can be swapped (ailink.js, "use as standard").
  document.addEventListener("click", function (event) {
    var manage = event.target.closest('[data-manage="claude"]');
    var openButton = event.target.closest("#claude-open");
    var out = dialog.querySelector("[data-to-disconnect]");   // "disconnect" next to "renew" of an expired sign-in
    if (manage) {
      reset();
      show(manage.dataset.plan === "connected" ? "plan-on" : "start");
      if (out) out.hidden = true;
      dialog.showModal();
    } else if (openButton) {
      reset();
      // nothing starts until the user wants the plan (the right half may be all he wants: an API key)
      show(openButton.dataset.status === "connected" ? "disconnect" : "start");
      if (out) out.hidden = openButton.dataset.status !== "expired";
      dialog.showModal();
    }
  });


  var startButton = dialog.querySelector("[data-start]");
  if (startButton) startButton.addEventListener("click", function () {
    show("wait");
    since = Date.now();
    post("/claude/connect").then(function (data) {
      if (!data.ok) return end("failed");
      started = true;
      poll();
    });
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!window.AgentHub.validate(form)) return;
    post("/claude/code", new FormData(form)).then(function (data) {
      if (data.ok) { submitted = true; show("check"); }
      else end("failed");
    });
  });

  dialog.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-cancel")) dialog.close();       // the close handler cancels the login
    else if (button.hasAttribute("data-to-disconnect")) show("disconnect");
    else if (button.hasAttribute("data-finish-keep")) { finished = true; dialog.close(); }
    else if (button.hasAttribute("data-finish")) { dialog.close(); window.AgentHub.reload(); }
    else if (button.hasAttribute("data-disconnect")) {   // the drawer's "disconnect": the plan and the API key
      finished = true;
      post("/claude/disconnect").then(function () { return post("/ai/claude/api/remove"); })
        .then(function () { dialog.close(); window.AgentHub.reload(); });
    }
    else if (button.hasAttribute("data-plan-off")) {     // only the plan; the key stays
      button.disabled = true;
      post("/claude/disconnect").then(function () { button.disabled = false; changed = true; show("start"); });
    }
  });

  // Closed in any way (button, Escape): stop asking, and cancel a login that is still waiting.
  dialog.addEventListener("close", function () {
    stop();
    if (started && !finished) { finished = true; post("/claude/disconnect"); }
    if (changed || dialog.dataset.apiChanged) { delete dialog.dataset.apiChanged; window.AgentHub.reload(); }
  });
})();
