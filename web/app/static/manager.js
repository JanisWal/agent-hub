// Settings of the manager in the Manager view (routes/manager.py): model and effort level, how freely it decides and
// the switch "web and code together". They hold for everything the manager does, so a change is saved at once.
// The server answers with all settings as it has them now; the controls show that (after a new model the level can
// have become the model's default). If saving fails, the control goes back to the value the server had.
(function () {
  var selects = document.querySelectorAll("#manager-view select[data-setting]");

  function save(name, value, done) {
    var data = new FormData();
    data.append(name, value);
    fetch("/manager/settings", { method: "POST", body: data })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (answer) { done(answer.ok ? answer : null); })
      .catch(function () { done(null); });
  }

  var saved = {};
  selects.forEach(function (select) { saved[select.dataset.setting] = select.value; });

  function show(answer) {
    selects.forEach(function (select) {
      var name = select.dataset.setting;
      if (answer && answer[name]) saved[name] = answer[name];
      select.value = saved[name];
      if (window.AgentHub && window.AgentHub.syncPicker) window.AgentHub.syncPicker(select);
    });
  }

  selects.forEach(function (select) {
    select.addEventListener("change", function () {
      save(select.dataset.setting, select.value, show);
    });
  });

  // A switch: checked = its data-on value, unchecked = its data-off value.
  document.querySelectorAll("#manager-view input[type=checkbox][data-setting]").forEach(function (box) {
    var was = box.checked;
    box.addEventListener("change", function () {
      save(box.dataset.setting, box.checked ? box.dataset.on : box.dataset.off, function (answer) {
        var value = answer && answer[box.dataset.setting];
        if (value) was = value === box.dataset.on;
        box.checked = was;
      });
    });
  });
})();
