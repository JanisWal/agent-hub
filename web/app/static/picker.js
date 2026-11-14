// The model picker (ui.model_picker): AI model and effort level as two drop-downs. The level list holds every level
// of the provider; this script hides the ones the chosen model does not have, and when the chosen level is not
// available any more it takes the model's default level (the server does the same, catalog.resolve).
// AgentHub.syncPicker(element) does it again after a script set the values itself (manager.js after saving).
(function () {
  function sync(picker) {
    var model = picker.querySelector('select[name="model"]');
    var effort = picker.querySelector('select[name="effort"]');
    if (!model || !effort) return;
    var levels = {}, defaults = {};
    try {
      levels = JSON.parse(effort.dataset.levels || "{}");
      defaults = JSON.parse(effort.dataset.defaults || "{}");
    } catch (e) { return; }
    var allowed = levels[model.value] || [];
    Array.prototype.forEach.call(effort.options, function (option) {
      option.hidden = allowed.indexOf(option.value) < 0;
    });
    if (allowed.indexOf(effort.value) < 0 && defaults[model.value]) effort.value = defaults[model.value];
  }

  document.querySelectorAll(".model-picker").forEach(function (picker) {
    var model = picker.querySelector('select[name="model"]');
    if (model) model.addEventListener("change", function () { sync(picker); });
    sync(picker);
  });

  window.AgentHub = window.AgentHub || {};
  window.AgentHub.syncPicker = function (element) {
    var picker = element && element.closest(".model-picker");
    if (picker) sync(picker);
  };
})();
