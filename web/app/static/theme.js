// Runs in <head> before the first paint (no defer): applies the saved theme, so the page never flashes in the other
// style, and switches off the entrance animation after a reload we triggered ourselves ("noanim", see core.js).
// A file of its own, not inline: the content security policy (main.py) allows scripts from /static only.
try {
  var t = localStorage.getItem("theme");
  if (t) document.documentElement.dataset.theme = t;
  if (sessionStorage.getItem("noanim")) {
    document.documentElement.classList.add("noanim");
    sessionStorage.removeItem("noanim");
  }
} catch (e) {}
