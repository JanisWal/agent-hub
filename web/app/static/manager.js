// Settings of the manager in the Manager view (routes/manager.py): the model and how freely it decides.
// They hold for everything the manager does, so a change is saved at once. If saving fails, the drop-down
// goes back to the value the server has.
(function () {
  document.querySelectorAll("#manager-view select[data-setting]").forEach(function (select) {
    var saved = select.value;
    select.addEventListener("change", function () {
      var data = new FormData();
      data.append(select.dataset.setting, select.value);
      fetch("/manager/settings", { method: "POST", body: data })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (answer) {
          if (answer.ok) saved = answer[select.dataset.setting] || select.value;
          select.value = saved;
        })
        .catch(function () { select.value = saved; });
    });
  });
})();
