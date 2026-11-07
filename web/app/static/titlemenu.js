/* The pencil next to the project title opens a drop-down with name and description (Janis, 07.11.2026).
   It closes with a click elsewhere, with Escape, with "Cancel" and after saving (the page reloads). */
(function () {
  "use strict";
  var button = document.getElementById("title-edit");
  var menu = document.getElementById("title-menu");
  if (!button || !menu) return;

  function setOpen(open) {
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) {
      menu.classList.remove("appear");
      void menu.offsetWidth;
      menu.classList.add("appear");
      var first = menu.querySelector("input");
      if (first) first.focus();
    }
  }

  button.addEventListener("click", function () { setOpen(menu.hidden); });
  menu.querySelector("[data-close]").addEventListener("click", function () { setOpen(false); button.focus(); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !menu.hidden) { setOpen(false); button.focus(); }
  });
  document.addEventListener("click", function (event) {
    if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) setOpen(false);
  });
})();
