/* Stations of the project page: a click on a station swaps the main window, the list stays. Every view is an element
   with data-view-panel="<name>" (board, manager, the role views and "for you", rolepage.py).
   The view lives in the address (#board, #manager, #programmer, ...), so a reload, the back button and a link keep it.
   Each area keeps its own controls (Janis, 11.11.2026): the trash and archive buttons belong to the board, the
   manager has its own pair; on the role views neither shows (body data-open-view, see project.css). */
(function () {
  "use strict";
  var project = document.querySelector(".project");
  if (!project) return;
  var panels = {};
  project.querySelectorAll("[data-view-panel]").forEach(function (el) { panels[el.dataset.viewPanel] = el; });
  var links = project.querySelectorAll("a.station[data-station]");
  var current = "board";
  var nav = project.querySelector(".stations");
  // The same segment slider as the file tabs (segment.js), upright here: the thumb lies under the open station and
  // can be dragged to another one.
  var segment = Segment.attach(nav, {
    thumb: nav.querySelector(".station-thumb"),
    items: function () { return Array.prototype.slice.call(nav.querySelectorAll(".station")); },
    current: function () { return nav.querySelector(".station.active"); },
    enabled: function (el) { return !el.classList.contains("off"); },
    pick: function (el) { show(el.dataset.station, true); }
  });

  function show(name, animate) {
    if (!panels[name]) name = "board";
    if (name !== "board") {
      // Close an open trash or archive list first, so the board is clean when it comes back.
      var open = document.querySelector('.drawer-extra[aria-controls="vault"][aria-pressed="true"]');
      if (open) open.click();
    }
    if (name !== "manager" && window.AgentHub && window.AgentHub.closeManagerVault) {
      window.AgentHub.closeManagerVault();   // trash or chat archive of the Manager closes with the view
    }
    current = name;
    document.body.classList.toggle("manager-open", name === "manager");
    document.body.dataset.openView = name;
    Object.keys(panels).forEach(function (key) { panels[key].hidden = key !== name; });
    Array.prototype.forEach.call(links, function (link) {
      var on = link.dataset.station === name;
      link.classList.toggle("active", on);
      if (on) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    segment.place(!animate);
    // Narrow windows: the stations are a row that scrolls sideways; the open one moves into the middle of it.
    var open = nav.querySelector(".station.active");
    if (open && nav.scrollWidth > nav.clientWidth) {
      var still = !animate || matchMedia("(prefers-reduced-motion: reduce)").matches;
      nav.scrollTo({ left: open.offsetLeft - (nav.clientWidth - open.offsetWidth) / 2, behavior: still ? "auto" : "smooth" });
    }
    if (animate) {   // a short fade, restarted each time
      panels[name].classList.remove("appear");
      void panels[name].offsetWidth;
      panels[name].classList.add("appear");
      try { history.replaceState(null, "", "#" + name); } catch (e) {}
    }
    document.dispatchEvent(new CustomEvent("agenthub:view", { detail: name }));
  }

  Array.prototype.forEach.call(links, function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      if (link.dataset.station === current) return;
      show(link.dataset.station, true);
    });
  });
  // A link inside a view that leads to another view ("To the board" in "For you").
  document.addEventListener("click", function (event) {
    var go = event.target.closest && event.target.closest("a[data-goto]");
    if (!go) return;
    event.preventDefault();
    show(go.dataset.goto, true);
  });

  show(location.hash.slice(1) || "board", false);
})();
