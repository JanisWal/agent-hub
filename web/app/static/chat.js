// The chat window of the project page (see web/app/chat.py). Shows the latest questions and
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

  function line(kind, who, text) {
    var item = document.createElement("li");
    item.className = "chat-msg " + kind;
    var name = document.createElement("span");
    name.className = "chat-who";
    name.textContent = who;
    var body = document.createElement("span");
    body.className = "chat-text";
    body.textContent = text;
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
        log.appendChild(line("claude", box.dataset.claude, m.answer));
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

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!window.AgentHub.validate(form)) return;
    problem("");
    fetch(url, { method: "POST", body: new FormData(form) })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        if (data.ok) { form.reset(); load(); } else problem(data.message || "");
      })
      .catch(function () {});
  });

  // On narrow screens the window is hidden behind a round button (CSS shows it on wide screens always).
  var toggle = document.getElementById("chat-toggle");
  function setOpen(open, focus) {
    document.body.classList.toggle("chat-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    try { sessionStorage.setItem("chatOpen", open ? "1" : ""); } catch (e) {}
    if (open && focus) { var field = form.querySelector("input"); if (field) field.focus(); }
  }
  if (toggle) {
    toggle.addEventListener("click", function () { setOpen(!document.body.classList.contains("chat-open"), true); });
    try { if (sessionStorage.getItem("chatOpen")) setOpen(true, false); } catch (e) {}
  }

  load();
})();
