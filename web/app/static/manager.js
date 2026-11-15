// Settings of an agent, saved at once: the Manager view (routes/manager.py: model and effort level, how freely it
// decides, "web and code together") and since 15.11.2026 the role views (routes/roles.py: on or off, the same switch,
// model and level). Each area names its address in data-settings-url; the same code serves all of them.
// The server answers with all settings as it has them now; the controls show that (after a new model the level can
// have become the model's default). If saving fails, the control goes back to the value the server had.
document.querySelectorAll("[data-settings-url]").forEach(function (area) {
  var selects = area.querySelectorAll("select[data-setting]");

  function save(name, value, done) {
    var data = new FormData();
    data.append(name, value);
    fetch(area.dataset.settingsUrl, { method: "POST", body: data })
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

  // A pill that is pressed or not (aria-pressed): pressed = its data-on value, else its data-off value. It changes at
  // once on the click and goes back if the server does not take it.
  area.querySelectorAll("button[aria-pressed][data-setting]").forEach(function (pill) {
    var was = pill.getAttribute("aria-pressed") === "true";
    pill.addEventListener("click", function () {
      var on = pill.getAttribute("aria-pressed") !== "true";
      pill.setAttribute("aria-pressed", String(on));
      save(pill.dataset.setting, on ? pill.dataset.on : pill.dataset.off, function (answer) {
        var value = answer && answer[pill.dataset.setting];
        if (value) was = value === pill.dataset.on;
        pill.setAttribute("aria-pressed", String(was));
      });
    });
  });
});
