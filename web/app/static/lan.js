// The owner's approvals of the home network for other users' devices (adminpage.lan_block, 17.11.2026): one button
// per device, approve or block; the row stays, only the button's word changes. Texts from data-* of the block.
(function () {
  "use strict";
  var block = document.querySelector(".lan-wrap");
  if (!block) return;
  block.addEventListener("click", function (event) {
    var button = event.target.closest("[data-lan]");
    if (!button) return;
    var row = button.closest(".lan-row");
    var body = new FormData();
    body.append("allowed", button.dataset.lan);
    button.disabled = true;
    fetch("/admin/devices/" + row.dataset.id + "/lan", { method: "POST", body: body, credentials: "same-origin" })
      .then(function (response) {
        button.disabled = false;
        if (!response.ok) return;
        var allowed = button.dataset.lan === "1";
        button.dataset.lan = allowed ? "0" : "1";
        button.textContent = allowed ? block.dataset.revoke : block.dataset.allow;
      }, function () { button.disabled = false; });
  });
})();
