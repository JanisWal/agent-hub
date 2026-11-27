// The model picker (ui.model_picker): AI model and effort level as two drop-downs. The level list holds every level
// of the provider; this script hides the ones the chosen model does not have, and when the chosen level is not
// available any more it takes the model's default level (the server does the same, catalog.resolve).
// An AI chosen by strength (catalog.by_strength, Janis 27.11.2026): the third box (weak, middle, strong) stands in
// place of the levels, and the model list shows only that AI's models of the chosen strength. Choosing another
// strength takes its first model when the chosen one is not of it; only the model is saved (manager.js).
// AgentHub.syncPicker(element) does it again after a script set the values itself (manager.js after saving).
(function () {
  function read(select, key) {
    try { return JSON.parse((select && select.dataset[key]) || "{}"); } catch (e) { return null; }
  }

  function sync(picker) {
    var model = picker.querySelector('select[name="model"]');
    var effort = picker.querySelector('select[name="effort"]');
    if (!model || !effort) return;
    var strength = picker.querySelector('select[id$="-strength"]');
    var levels = read(effort, "levels"), defaults = read(effort, "defaults"), strengths = read(strength, "strengths") || {};
    if (!levels || !defaults) return;
    var own = strengths[model.value];
    if (strength) {
      strength.closest("label").hidden = !own;
      if (own) strength.value = own;
    }
    effort.closest("label").hidden = !!own;
    Array.prototype.forEach.call(model.options, function (option) {   // other strengths of the same AI step aside
      option.hidden = !!own && option.value in strengths && strengths[option.value] !== own;
    });
    var allowed = levels[model.value] || [];
    Array.prototype.forEach.call(effort.options, function (option) {
      option.hidden = allowed.indexOf(option.value) < 0;
    });
    if (allowed.indexOf(effort.value) < 0 && defaults[model.value]) effort.value = defaults[model.value];
  }

  function choose(picker) {   // a strength was chosen: keep the model if it is of it, else the first one of it
    var model = picker.querySelector('select[name="model"]');
    var strength = picker.querySelector('select[id$="-strength"]');
    var strengths = read(strength, "strengths") || {};
    if (!model || strengths[model.value] === strength.value) return;
    var first = Array.prototype.find.call(model.options, function (option) {
      return strengths[option.value] === strength.value;
    });
    if (!first) return;
    model.value = first.value;
    model.dispatchEvent(new Event("change"));   // manager.js saves it, the listener below syncs
  }

  document.querySelectorAll(".model-picker").forEach(function (picker) {
    var model = picker.querySelector('select[name="model"]');
    var strength = picker.querySelector('select[id$="-strength"]');
    if (model) model.addEventListener("change", function () { sync(picker); });
    if (strength) strength.addEventListener("change", function () { choose(picker); });
    sync(picker);
  });

  window.AgentHub = window.AgentHub || {};
  // After the AI of a role (or the standard) changed: every picker takes the list, levels and value the server
  // draws now (`fresh`: the page as AgentHub.swap returns it). The selects stay, so their listeners keep working.
  // A picker the user has open is left alone.
  window.AgentHub.refreshPickers = function (fresh) {
    document.querySelectorAll(".model-picker select[id]").forEach(function (select) {
      var next = fresh.getElementById(select.id);
      if (!next || document.activeElement === select) return;
      ["levels", "defaults", "strengths"].forEach(function (key) {
        if (next.dataset[key] !== undefined) select.dataset[key] = next.dataset[key];
      });
      if (select.innerHTML !== next.innerHTML) {
        select.innerHTML = next.innerHTML;
        select.dispatchEvent(new Event("agenthub:options"));   // core.js builds its list of entries again
      }
      select.value = next.value;
      var picker = select.closest(".model-picker"), nextPicker = next.closest(".model-picker");
      if (picker && nextPicker) picker.dataset.provider = nextPicker.dataset.provider;
    });
    document.querySelectorAll(".model-picker").forEach(sync);
  };
  window.AgentHub.syncPicker = function (element) {
    var picker = element && element.closest(".model-picker");
    if (picker) sync(picker);
  };
})();
