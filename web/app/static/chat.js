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
      target.appendChild(pre);
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
    item.appendChild(name);
    item.appendChild(body);
    return item;
  }

  function render(messages) {
    log.textContent = "";
    var open = false;
    messages.forEach(function (m) {
      log.appendChild(line("you", box.dataset.you, m.prompt));
      if (m.status === "queued" || m.status === "running") {
        open = true;
        log.appendChild(line("claude wait", box.dataset.claude, box.dataset.waiting));
      } else if (m.status === "failed") {
        log.appendChild(line("claude failed", box.dataset.claude, box.dataset.failed + (m.answer ? ": " + m.answer : "")));
      } else {
        log.appendChild(line("claude", box.dataset.claude, m.answer, true));
      }
    });
    send.disabled = open;
    log.scrollTop = log.scrollHeight;
    clearTimeout(timer);
    if (open) timer = setTimeout(load, 2000);
  }

  function load() {
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      if (data.ok) render(data.messages);
    }).catch(function () { timer = setTimeout(load, 4000); });
  }

  function problem(text) {
    errorBox.hidden = !text;
    errorBox.textContent = text || "";
  }

  // The manager uses web and code only when a question needs them. The model and the web/code switch are the
  // manager's settings (tile header, saved by manager.js); the server picks them up for every question.
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!window.AgentHub.validate(form)) return;
    problem("");
    var data = new FormData(form);
    fetch(url, { method: "POST", body: data })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        if (data.ok) { form.reset(); load(); } else problem(data.message || "");
      })
      .catch(function () {});
  });

  load();
})();
