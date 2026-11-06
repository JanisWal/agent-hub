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
  function problem(input) {
    if (input.value === "" || (input.type !== "password" && input.value.trim() === "")) {
      return "Bitte ausfüllen.";
    }
    if (input.type === "email" && !input.checkValidity()) {
      return "Bitte eine gültige E-Mail-Adresse eingeben.";
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

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("novalidate")) return;
    var first = null;
    form.querySelectorAll("input[required]").forEach(function (input) {
      var text = problem(input);
      show(input, text);
      if (text && !first) first = input;
    });
    if (first) {
      event.preventDefault();
      first.focus();
    }
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("label.has-error input")) show(event.target, "");
  });
})();
