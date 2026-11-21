// A row that scrolls sideways ([data-hscroll], Janis 22.11.2026: the AIs of a role): the side wheel of a mouse and
// shift with the wheel scroll it natively; the plain wheel scrolls it too while the row is wider than its box; with the
// mouse it can be dragged. A drag is no click: a button in the row is not pressed when the row was moved.
(function () {
  "use strict";
  document.addEventListener("wheel", function (event) {
    var row = event.target.closest ? event.target.closest("[data-hscroll]") : null;
    if (!row || event.deltaX || row.scrollWidth <= row.clientWidth) return;
    row.scrollLeft += event.deltaY;
    event.preventDefault();
  }, { passive: false });

  var drag = null;
  document.addEventListener("pointerdown", function (event) {
    var row = event.target.closest ? event.target.closest("[data-hscroll]") : null;
    if (!row || event.pointerType !== "mouse" || event.button !== 0 || row.scrollWidth <= row.clientWidth) return;
    drag = { row: row, x: event.clientX, left: row.scrollLeft, moved: false };
  });
  document.addEventListener("pointermove", function (event) {
    if (!drag) return;
    var dx = event.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < 5) return;
    drag.moved = true;
    drag.row.classList.add("dragging");
    drag.row.scrollLeft = drag.left - dx;
  });
  document.addEventListener("pointerup", function () {
    if (!drag) return;
    var row = drag.row, moved = drag.moved;
    drag = null;
    row.classList.remove("dragging");
    if (moved) {   // the click that follows the drag is swallowed
      row.addEventListener("click", function stop(e) { e.stopPropagation(); e.preventDefault(); }, { capture: true, once: true });
    }
  });
})();
