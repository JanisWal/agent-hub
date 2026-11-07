/* Stations of the project page: a click on "Board" or "Manager" swaps the main window, the list stays.
   The view lives in the address (#board, #manager), so a reload, the back button and a link keep it.
   The trash and archive buttons belong to the board: while the manager is open they bring the board back. */
(function () {
  "use strict";
  var project = document.querySelector(".project");
  if (!project) return;
  var panels = {
    board: document.querySelector(".boardwrap"),
    manager: document.getElementById("manager-view")
  };
  var links = project.querySelectorAll("a.station[data-station]");
  var current = "board";

  function show(name, animate) {
    if (!panels[name]) name = "board";
    if (name === "manager") {
      // Close an open trash or archive list first, so the board is clean when it comes back.
      var open = document.querySelector('.drawer-extra[aria-pressed="true"]');
      if (open) open.click();
    }
    current = name;
    document.body.classList.toggle("view-manager", name === "manager");   // the old chat dock steps aside (project.css)
    Object.keys(panels).forEach(function (key) { panels[key].hidden = key !== name; });
    Array.prototype.forEach.call(links, function (link) {
      var on = link.dataset.station === name;
      link.classList.toggle("active", on);
      if (on) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    if (animate) {   // a short fade, restarted each time
      panels[name].classList.remove("appear");
      void panels[name].offsetWidth;
      panels[name].classList.add("appear");
      try { history.replaceState(null, "", "#" + name); } catch (e) {}   // also when the trash button brings the board back
    }
  }

  Array.prototype.forEach.call(links, function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      if (link.dataset.station === current) return;
      show(link.dataset.station, true);
    });
  });

  // Trash and archive: switch to the board first; board.js then opens the list (it was closed above).
  Array.prototype.forEach.call(document.querySelectorAll(".drawer-extra"), function (button) {
    button.addEventListener("click", function () { if (current !== "board") show("board", true); }, true);
  });

  show(location.hash === "#manager" ? "manager" : "board", false);
})();
