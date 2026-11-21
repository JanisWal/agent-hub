// The manager chat in the Manager view (see web/app/chat.py). Shows the latest questions and
// answers, sends a new question, and asks every 2 seconds while one is still open. Answers are
// text from Claude: they are only ever put in with textContent. All labels come from data-* attributes.
(function () {
  var box = document.getElementById("chat");
  if (!box) return;
  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var send = document.getElementById("chat-send");
  var errorBox = document.getElementById("chat-error");
  var input = document.getElementById("chat-input");
  var projectId = document.querySelector(".project").dataset.id;
  var url = "/projects/" + projectId + "/chat";
  var timer = null;

  // Answers may contain **bold**, [text](link) and bare links (after a web search). Built from DOM nodes only,
  // never from HTML, and only http(s) links: nothing in an answer can inject markup or a javascript: link.
  var TOKEN = /\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)<>\]]+)|`([^`\n]+)`/g;
  function fillRich(target, text) {
    var last = 0;
    var m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(text))) {
      if (m.index > last) target.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        var strong = document.createElement("strong");
        strong.textContent = m[1];
        target.appendChild(strong);
      } else if (m[5] !== undefined) {
        var inline = document.createElement("code");
        inline.textContent = m[5];
        target.appendChild(inline);
      } else {
        var link = document.createElement("a");
        link.href = m[3] || m[4];
        link.textContent = m[2] || m[4];
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        target.appendChild(link);
      }
      last = TOKEN.lastIndex;
    }
    if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
  }

  // ```code``` blocks become <pre><code>, the rest goes through fillRich.
  function fillBlocks(target, text) {
    var fence = /```[^\n]*\n?([\s\S]*?)```/g;
    var last = 0;
    var m;
    while ((m = fence.exec(text))) {
      if (m.index > last) fillRich(target, text.slice(last, m.index));
      var pre = document.createElement("pre");
      var code = document.createElement("code");
      code.textContent = m[1].replace(/\n$/, "");
      pre.appendChild(code);
      code.dataset.copyText = "";
      var box = document.createElement("div");   // a code block copies with one click (core.js)
      box.className = "copy-box chat-code";
      box.appendChild(pre);
      if (window.AgentHub.copyButton) box.appendChild(window.AgentHub.copyButton());
      target.appendChild(box);
      last = fence.lastIndex;
    }
    if (last < text.length) fillRich(target, text.slice(last));
  }

  function line(kind, who, text, rich) {
    var item = document.createElement("li");
    item.className = "chat-msg " + kind;
    var name = document.createElement("span");
    name.className = "chat-who";
    name.textContent = who;
    var body = document.createElement("span");
    body.className = "chat-text";
    if (rich) fillBlocks(body, text); else body.textContent = text;
    if (kind.indexOf("wait") >= 0) {   // something is under way: the shared three dots (app.css)
      var dots = document.createElement("span");
      dots.className = "loading-dots";
      dots.setAttribute("aria-hidden", "true");
      for (var d = 0; d < 3; d++) dots.appendChild(document.createElement("i"));
      body.appendChild(dots);
    }
    item.appendChild(name);
    item.appendChild(body);
    return item;
  }

  // The thoughts of the AI (Janis, 18.11.2026): open while it works, folded above the answer once it is there, a click
  // opens them again. The log is rebuilt on every poll, so the user's choice, the last shown state (a change turns
  // the arrow with a spring) and where a box was scrolled are kept here by message id. Thoughts are plain text.
  var opened = {};
  var shownOpen = {};
  var scrolled = {};   // id -> scrollTop; missing = at the start (done) or following the end (running)

  function turn(mark, from, to) {
    var set = function (v) { mark.style.transform = "rotate(" + (v - 45) + "deg)"; };
    set(from ? 90 : 0);
    if (from !== to && window.Motion) Motion.spring(from ? 90 : 0, Motion.MOVE, set).to(to ? 90 : 0);
    else set(to ? 90 : 0);
  }

  function fadeIn(el) {
    if (!window.Motion || Motion.reduced()) return;
    el.style.opacity = "0";
    Motion.spring(0, Motion.MOVE, function (v) { el.style.opacity = String(v); }, 0.01).to(1);
  }

  function addThoughts(item, m, running) {
    if (!m.thoughts) return;
    var open = m.id in opened ? opened[m.id] : running;
    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "chat-think";
    var mark = document.createElement("span");
    mark.className = "chat-think-mark";
    mark.setAttribute("aria-hidden", "true");
    toggle.appendChild(mark);
    toggle.appendChild(document.createTextNode(box.dataset.thoughts));
    var text = document.createElement("div");
    text.className = "chat-thoughts";
    text.id = "chat-thoughts-" + m.id;
    text.textContent = m.thoughts;
    if (running) text.dataset.running = "1";
    toggle.setAttribute("aria-controls", text.id);
    function show(now, before) {
      text.hidden = !now;
      toggle.setAttribute("aria-expanded", now ? "true" : "false");
      turn(mark, before, now);
      if (now && before === false) fadeIn(text);
      shownOpen[m.id] = now;
    }
    show(open, m.id in shownOpen ? shownOpen[m.id] : open);
    toggle.addEventListener("click", function () {
      opened[m.id] = text.hidden;
      show(opened[m.id], !opened[m.id]);
      if (opened[m.id]) place(text, m.id);
    });
    text.addEventListener("scroll", function () {
      var atEnd = text.scrollHeight - text.scrollTop - text.clientHeight < 20;
      if (text.dataset.running && atEnd) delete scrolled[m.id]; else scrolled[m.id] = text.scrollTop;
    });
    var body = item.querySelector(".chat-text");
    item.insertBefore(toggle, body);
    item.insertBefore(text, body);
  }

  // Where a thoughts box stands after a rebuild: where the user left it, else at the newest line while the AI thinks.
  function place(text, id) {
    if (id in scrolled) text.scrollTop = scrolled[id];
    else if (text.dataset.running) text.scrollTop = text.scrollHeight;
  }

  // "Claude is answering" with the AI of the chosen model (ui.model_picker puts its name on the option as data-ai).
  function waitingText() {
    var chosen = document.querySelector('#manager-model option:checked');
    return box.dataset.waiting.replace("{name}", (chosen && chosen.dataset.ai) || box.dataset.ai || "");
  }

  function render(messages) {
    log.textContent = "";
    var open = false;
    messages.forEach(function (m) {
      log.appendChild(line("you", box.dataset.you, m.prompt));
      if (m.status === "queued" || m.status === "running") {
        open = true;
        var waiting = line("claude wait", box.dataset.claude, waitingText());
        addThoughts(waiting, m, true);
        log.appendChild(waiting);
      } else if (m.status === "failed") {
        // Only a short text per kind of failure (chat.FAILURES), never what Claude Code said.
        var kind = { auth: "failAuth", timeout: "failTimeout", steps: "failSteps", limit: "failLimit", server: "failServer", plan: "failPlan" }[m.failure] || "failOther";
        log.appendChild(line("claude failed", box.dataset.claude, box.dataset.failed + ": " + box.dataset[kind]));
      } else {
        var answer = line("claude", box.dataset.claude, m.answer, true);
        addThoughts(answer, m, false);
        log.appendChild(answer);
        if (m.memory) log.appendChild(line("note", "", box.dataset.memory));   // the answer updated MEMORY.md
        // Another AI of the user answered because the first could not (aichoice.py): say which and why.
        if (m.via) log.appendChild(line("note", "", box.dataset.fallback.replace("{name}", m.via).replace("{other}", m.instead)));
      }
    });
    send.disabled = open;
    Array.prototype.forEach.call(log.querySelectorAll(".chat-thoughts:not([hidden])"), function (text) {
      place(text, Number(text.id.slice("chat-thoughts-".length)));
    });
    toEnd();
    clearTimeout(timer);
    if (open) timer = setTimeout(load, 2000);
  }

  // The chat stands at the newest answer (Janis, 15.11.2026). The answers may arrive while the Manager view is still
  // hidden (the page opens on the board): a hidden list has no height, so scrolling does nothing then. When the list
  // gets its size (the view opens, a tile is resized) it goes to the end again, unless the user scrolled up to read.
  var follow = true;
  function toEnd() { follow = true; log.scrollTop = log.scrollHeight; }
  log.addEventListener("scroll", function () {
    if (log.clientHeight) follow = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  });
  if (window.ResizeObserver) {
    new ResizeObserver(function () { if (follow) log.scrollTop = log.scrollHeight; }).observe(log);
  }

  function load() {
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.ok) return;
      render(data.messages);
      // A lost sign-in shows in the menu at once, not only after the next page load (claude.js).
      if (data.claude === "expired" && window.AgentHub && window.AgentHub.claudeExpired) window.AgentHub.claudeExpired();
    }).catch(function () { timer = setTimeout(load, 4000); });
  }

  document.addEventListener("hub:chat-changed", load);   // an answer from "waiting for you" went on as a message

  function problem(text) {
    errorBox.hidden = !text;
    errorBox.textContent = text || "";
  }

  // The field grows with what is written, up to three lines (Janis, 14.11.2026), then it scrolls inside.
  // max-height in project.css sets the limit; scrollHeight is read after the height went back to one line.
  function fit() {
    input.style.height = "auto";
    input.style.height = input.scrollHeight + 2 + "px";
  }
  input.addEventListener("input", fit);
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!send.disabled) form.requestSubmit();
    }
  });

  // The manager uses web and code only when a question needs them. The model and the web/code switch are the
  // manager's settings (tile header, saved by manager.js); the server picks them up for every question.
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!input.value.trim()) { input.focus(); return; }
    problem("");
    var data = new FormData(form);
    fetch(url, { method: "POST", body: data })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        if (data.ok) { form.reset(); fit(); load(); } else problem(data.message || "");
      })
      .catch(function () {});
  });

  load();
})();
