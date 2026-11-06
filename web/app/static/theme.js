// Theme toggle. The saved choice is applied earlier by a small inline script in <head>.
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
})();
