// Dashboard: greeting, "new project" dialog and the two-step delete dialog.
// Needs core.js. The page of tiles is pages.js.
(function () {
  function $(selector, root) { return (root || document).querySelector(selector); }

  // Greeting by the visitor's local time: 6-12 morning, 12-17 midday, 17-23 evening, 23-6 night.
  var greeting = $("#greeting");
  if (greeting) {
    var hour = new Date().getHours();
    var part = hour >= 6 && hour < 12 ? "morning" : hour >= 12 && hour < 17 ? "noon"
      : hour >= 17 && hour < 23 ? "evening" : "night";
    greeting.textContent = greeting.dataset[part] + ", " + greeting.dataset.name;
  }

  var createDialog = $("#create-dialog");
  var newProject = $("#new-project");
  if (createDialog && newProject) {
    newProject.addEventListener("click", function () {
      createDialog.showModal();
      $("input", createDialog).focus();
    });
    createDialog.addEventListener("close", function () {
      var form = $("form", createDialog);
      form.reset();
      AgentHub.clear(form);
    });
  }

  // Deleting: step 1 asks "sure?", step 2 asks for the password, both can be cancelled.
  var deleteDialog = $("#delete-dialog");
  if (deleteDialog) {
    var step1 = $('[data-step="1"]', deleteDialog);
    var step2 = $('[data-step="2"]', deleteDialog);
    var wrong = $("#delete-error");
    var wrongText = wrong.textContent; // the lock message replaces it for a while
    var password = $('input[name="password"]', deleteDialog);
    var projectId = null;

    deleteDialog.addEventListener("close", function () {
      step1.hidden = false;
      step2.hidden = true;
      wrong.hidden = true;
      password.value = "";
      AgentHub.clear(step2);
    });

    document.addEventListener("click", function (event) {
      var button = event.target.closest(".tile-delete");
      if (!button) return;
      projectId = button.dataset.id;
      $("#delete-name").textContent = $(".tile-name", button.closest(".tile")).textContent;
      deleteDialog.showModal();
    });

    $("[data-yes]", deleteDialog).addEventListener("click", function () {
      step1.hidden = true;
      step2.hidden = false;
      password.focus();
    });

    step2.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!AgentHub.validate(step2)) return;
      wrong.hidden = true;
      wrong.textContent = wrongText;
      fetch("/projects/" + projectId + "/delete", { method: "POST", body: new FormData(step2) })
        .then(function (response) {
          if (response.status === 403) {
            wrong.hidden = false;
            password.select();
          } else if (response.status === 429) {
            return response.json().then(function (data) {
              wrong.textContent = data.message;
              wrong.hidden = false;
            });
          } else {
            AgentHub.reload();
          }
        })
        .catch(function () { wrong.hidden = false; });
    });
  }
})();
