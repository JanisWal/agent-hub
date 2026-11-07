// Loaded on every page: theme toggle, form validation, settings drawer, dialog buttons and
// the quiet reload. Published as window.AgentHub for the page scripts.
// The saved theme is applied earlier by a small inline script in <head> (layout.py).
(function () {
  var root = document.documentElement;

  function isDark() {
    var chosen = root.dataset.theme;
    if (chosen) return chosen === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest("#theme-toggle")) return;
    var next = isDark() ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  });

  // Reload after our own change: no entrance animation again, and stay where you were (lists scroll).
  function reload(url) {
    try {
      sessionStorage.setItem("noanim", "1");
      sessionStorage.setItem("scrollY", String(window.scrollY));
    } catch (e) {}
    if (url) location.assign(url); else location.reload();
  }
  try {
    var savedScroll = sessionStorage.getItem("scrollY");
    if (savedScroll !== null) { sessionStorage.removeItem("scrollY"); window.scrollTo(0, Number(savedScroll)); }
  } catch (e) {}

  // Forms marked novalidate get our own messages instead of the browser bubble.
  // The texts come from data-msg-required / data-msg-email on the form (translated by the server).
  function problem(input) {
    var texts = input.form ? input.form.dataset : {};
    if (input.value === "" || (input.type !== "password" && input.value.trim() === "")) {
      return texts.msgRequired || "";
    }
    if (input.type === "email" && !input.checkValidity()) return texts.msgEmail || "";
    return "";
  }

  function show(input, text) {
    var label = input.closest("label");
    var msg = label.querySelector(".field-msg");
    if (!text) {
      if (msg) msg.remove();
      label.classList.remove("has-error");
      input.removeAttribute("aria-invalid");
      return;
    }
    if (!msg) {
      msg = document.createElement("span");
      msg.className = "field-msg";
      msg.setAttribute("role", "alert");
      label.appendChild(msg);
    }
    msg.textContent = text;
    label.classList.add("has-error");
    input.setAttribute("aria-invalid", "true");
  }

  // Checks all required fields, shows messages, focuses the first bad one. True if all fine.
  function validate(form) {
    var first = null;
    form.querySelectorAll("input[required]").forEach(function (input) {
      var text = problem(input);
      show(input, text);
      if (text && !first) first = input;
    });
    if (first) first.focus();
    return !first;
  }

  function clear(form) {
    form.querySelectorAll("input").forEach(function (input) {
      if (input.closest("label")) show(input, "");
    });
  }

  window.AgentHub = { validate: validate, clear: clear, reload: reload };

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("novalidate")) return;
    if (!validate(form)) event.preventDefault();
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("label.has-error input")) show(event.target, "");
  });

  // Settings drawer: slides out of the top right corner, the handle rides along.
  var drawer = document.getElementById("settings");
  var toggle = document.getElementById("settings-toggle");
  if (drawer && toggle) {
    var setOpen = function (open) {
      drawer.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    var isOpen = function () { return drawer.classList.contains("open"); };
    toggle.addEventListener("click", function () { setOpen(!isOpen()); });
    document.addEventListener("click", function (event) {
      if (isOpen() && !event.target.closest("#settings")) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) setOpen(false);
    });
  }

  // Dialogs: every [data-close] button closes the dialog it is in.
  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-close]");
    if (close) close.closest("dialog").close();
  });
})();
