// Theme toggle and inline form validation.
// The saved theme is applied earlier by a small inline script in <head>.
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

  // Forms marked novalidate get our own messages instead of the browser bubble.
  // The texts come from data-msg-required / data-msg-email on the form (translated by the server).
  function problem(input) {
    var texts = input.form ? input.form.dataset : {};
    if (input.value === "" || (input.type !== "password" && input.value.trim() === "")) {
      return texts.msgRequired || "Bitte ausfüllen.";
    }
    if (input.type === "email" && !input.checkValidity()) {
      return texts.msgEmail || "Bitte eine gültige E-Mail-Adresse eingeben.";
    }
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

  window.AgentHub = { validate: validate, clear: clear };

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("novalidate")) return;
    if (!validate(form)) event.preventDefault();
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("label.has-error input")) show(event.target, "");
  });
})();
