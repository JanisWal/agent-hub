// Settings of the manager in the Manager view (routes/manager.py): the model, how freely it decides and the
// switch "web and code together". They hold for everything the manager does, so a change is saved at once.
// If saving fails, the control goes back to the value the server has.
(function () {
  function save(name, value, done) {
    var data = new FormData();
    data.append(name, value);
    fetch("/manager/settings", { method: "POST", body: data })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (answer) { done(answer.ok ? answer[name] : null); })
      .catch(function () { done(null); });
  }

  document.querySelectorAll("#manager-view select[data-setting]").forEach(function (select) {
    var saved = select.value;
    select.addEventListener("change", function () {
      save(select.dataset.setting, select.value, function (value) {
        if (value) saved = value;
        select.value = saved;
      });
    });
  });

  // A switch: checked = its data-on value, unchecked = its data-off value.
  document.querySelectorAll("#manager-view input[type=checkbox][data-setting]").forEach(function (box) {
    var saved = box.checked;
    box.addEventListener("change", function () {
      save(box.dataset.setting, box.checked ? box.dataset.on : box.dataset.off, function (value) {
        if (value) saved = value === box.dataset.on;
        box.checked = saved;
      });
    });
  });
})();
