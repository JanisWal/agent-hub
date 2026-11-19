// "Waiting for you" (Janis, 19.11.2026): answer a question of the manager or a role (a suggested answer with one
// click, or your own text) and decide about a task (approve, another round with a remark, cancel) right in the tile.
// After it was sent only the tile swaps (and the board, the chat); an answer to the manager goes on as a chat message.
(function () {
  var tile = document.getElementById("waiting");
  if (!tile) return;
  var errorBox = document.getElementById("waiting-error");
  function say(text) { errorBox.textContent = text || ""; errorBox.hidden = !text; }
  function send(item, url, values) {
    var body = new FormData();
    Object.keys(values).forEach(function (key) { body.append(key, values[key]); });
    item.classList.add("sending");
    say("");
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || !data.ok) throw new Error(data.message || tile.dataset.errNet || "");
        return data;
      });
    }).then(function (data) {
      if (data.sent) document.dispatchEvent(new CustomEvent("hub:chat-changed"));
      var parts = ["waiting"].concat(document.getElementById("board") ? ["board"] : []);
      return AgentHub.swap(parts).catch(function () { AgentHub.reload(); });
    }, function (problem) { item.classList.remove("sending"); say(problem.message); });
  }
  function answer(item, text) {
    if (!text.trim()) { item.querySelector(".w-input").focus(); return; }
    send(item, "/questions/" + item.dataset.question + "/answer", { answer: text });
  }
  document.addEventListener("click", function (event) {
    var item = event.target.closest("#waiting .w-item");
    if (!item) return;
    var reply = event.target.closest("[data-reply]");
    if (reply) { answer(item, reply.dataset.reply); return; }
    if (event.target.closest("[data-send]")) { answer(item, item.querySelector(".w-input").value); return; }
    var decide = event.target.closest("[data-decide]");
    if (decide) {
      send(item, "/tasks/" + item.dataset.task + "/decide",
           { decision: decide.dataset.decide, note: item.querySelector(".w-input").value });
    }
  });
  document.addEventListener("keydown", function (event) {   // Enter in an answer field sends it
    var input = event.target.closest && event.target.closest("#waiting .w-ask .w-input");
    if (input && event.key === "Enter" && !event.isComposing) { event.preventDefault(); answer(input.closest(".w-item"), input.value); }
  });
})();
