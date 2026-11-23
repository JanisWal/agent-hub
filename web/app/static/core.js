// Loaded on every page: theme toggle, form validation, settings drawer, dialog buttons and
// the quiet reload. Published as window.AgentHub for the page scripts.
// The saved theme is applied earlier by theme.js in <head> (layout.py).
(function () {
  var root = document.documentElement;

  function isDark() {
    var chosen = root.dataset.theme;
    if (chosen) return chosen === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest("#theme-toggle")) return;
    var next = isDark() ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  });

  // Reload after our own change: no entrance animation again, and stay where you were (lists scroll).
  // Reload as little as possible (Janis, 14.11.2026, a design rule: a reload broke a running upload). `swap(ids)`
  // fetches the page again and puts the new content of these elements in place; the elements themselves stay, so
  // listeners on them keep working. Work that a reload would break holds it (`hold(true)` ... `hold(false)`): a
  // reload asked for meanwhile waits until nothing is held.
  //
  // One way to update every page (Janis, 22.11.2026: "fast, at once, without the user noticing a reload"):
  // - swap(ids): all swaps asked for in the same moment share one request; a part whose content is what the server
  //   sent last time is left alone (nothing flickers, an opened detail stays open).
  // - act(url, body, {gone, parts}): an action the user sees at once. `gone` (a row, a card) folds away with a spring
  //   before the server answers, the rows below move up; then `parts` are swapped. If the server refuses, the parts
  //   are swapped anyway, so the row comes back as it is. While an action is on its way no live look runs.
  // - live({parts | run, every, when}): one timer for all parts of a page that follow the server by themselves. It
  //   waits while the page is hidden, a dialog is open, something is dragged, the user types in a field, or a reload
  //   is held. `parts` and `every` may be functions (asked each time); `run` is for a part with its own request.
  var sent = {};                 // id -> the content the server sent last for it
  var batch = null;              // the swap being collected in this moment
  function swap(ids) {
    if (!batch) {
      batch = { ids: {}, waiting: [] };
      Promise.resolve().then(flush);
    }
    ids.forEach(function (id) { batch.ids[id] = true; });
    return new Promise(function (resolve, reject) { batch.waiting.push({ ids: ids, resolve: resolve, reject: reject }); });
  }
  function flush() {
    var mine = batch;
    batch = null;
    fetch(location.pathname + location.search, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("swap");
      return response.text();
    }).then(function (html) {
      var fresh = new DOMParser().parseFromString(html, "text/html");
      fresh.changed = [];        // the ids whose content was replaced (a caller may skip its own work when none)
      Object.keys(mine.ids).forEach(function (id) {
        var now = document.getElementById(id), next = fresh.getElementById(id);
        if (!now || !next) return;
        var before = id in sent ? sent[id] : now.innerHTML;
        sent[id] = next.innerHTML;
        if (next.innerHTML !== before) { now.innerHTML = next.innerHTML; fresh.changed.push(id); }
      });
      mine.waiting.forEach(function (w) {
        var missing = w.ids.some(function (id) { return !document.getElementById(id) || !fresh.getElementById(id); });
        if (missing) w.reject(new Error("swap")); else w.resolve(fresh);   // ailink.js takes more from `fresh`
      });
    }).catch(function (error) {
      mine.waiting.forEach(function (w) { w.reject(error); });
    });
  }

  var acting = 0;
  function fold(el) {            // the row folds away: height, opacity and a little scale, then it is hidden
    var height = el.getBoundingClientRect().height;
    el.dataset.leaving = "1";
    el.style.overflow = "hidden";
    el.style.pointerEvents = "none";
    if (!window.Motion || Motion.reduced()) { el.hidden = true; return; }
    var style = getComputedStyle(el), my = parseFloat(style.marginTop) || 0, mb = parseFloat(style.marginBottom) || 0;
    var spring = Motion.spring(1, Motion.MOVE, function (v) {
      v = Math.max(0, v);
      el.style.opacity = String(v);
      el.style.transform = "scale(" + (0.96 + 0.04 * v) + ")";
      el.style.height = height * v + "px";
      el.style.marginTop = my * v + "px";
      el.style.marginBottom = mb * v + "px";
      if (v === 0) el.hidden = true;
    }, 0.002);
    spring.to(0);
  }
  function unfold(el) {
    ["overflow", "pointerEvents", "opacity", "transform", "height", "marginTop", "marginBottom"].forEach(function (k) { el.style[k] = ""; });
    el.hidden = false;
    delete el.dataset.leaving;
  }
  function act(url, body, options) {
    options = options || {};
    var gone = options.gone, parts = options.parts || [];
    acting += 1;
    if (gone) fold(gone);
    var init = { method: "POST", credentials: "same-origin" };
    if (body) init.body = body;
    return fetch(url, init).then(function (response) {
      var ok = response.ok;
      if (!ok && gone) unfold(gone);
      return (parts.length ? swap(parts) : Promise.resolve()).then(function () { return response; });
    }, function (error) {
      if (gone) unfold(gone);
      throw error;
    }).finally(function () { acting -= 1; });
  }

  var watchers = [];
  function quiet() {
    if (document.hidden || holds || acting || batch) return false;
    if (document.querySelector("dialog[open]") || root.classList.contains("dragging-active")) return false;
    var typing = document.activeElement;
    return !(typing && typing.matches && typing.matches("input, textarea, select, [contenteditable]") && typing.closest("[data-live-part], .role-view, #board, .dash"));
  }
  function value(x) { return typeof x === "function" ? x() : x; }
  function live(options) {
    var watcher = { options: options, due: Date.now() + (value(options.every) || 10000) };
    watchers.push(watcher);
    return { soon: function () { watcher.due = Date.now(); } };
  }
  setInterval(function () {
    if (!watchers.length || !quiet()) return;
    var now = Date.now();
    watchers.forEach(function (w) {
      if (w.busy || w.due > now) return;
      var o = w.options;
      if (o.when && !o.when()) { w.due = now + (value(o.every) || 10000); return; }
      w.busy = true;
      var done = function () { w.busy = false; w.due = Date.now() + (value(o.every) || 10000); };
      var job = o.run ? o.run() : swap(value(o.parts) || []);
      Promise.resolve(job).then(done, done);
    });
  }, 1000);

  var holds = 0, waiting = null;
  function hold(on) {
    holds = Math.max(0, holds + (on ? 1 : -1));
    if (!holds && waiting) { var url = waiting.url; waiting = null; reload(url); }
  }
  function reload(url) {
    if (holds) { waiting = { url: url }; return; }
    try {
      sessionStorage.setItem("noanim", "1");
      sessionStorage.setItem("scrollY", String(window.scrollY));
    } catch (e) {}
    if (url) location.assign(url); else location.reload();
  }
  try {
    var savedScroll = sessionStorage.getItem("scrollY");
    if (savedScroll !== null) { sessionStorage.removeItem("scrollY"); window.scrollTo(0, Number(savedScroll)); }
  } catch (e) {}

  // Forms marked novalidate get our own messages instead of the browser bubble.
  // The texts come from data-msg-required / data-msg-email on the form (translated by the server).
  function problem(input) {
    var texts = input.form ? input.form.dataset : {};
    if (input.value === "" || (input.type !== "password" && input.value.trim() === "")) {
      return texts.msgRequired || "";
    }
    if (input.type === "email" && !input.checkValidity()) return texts.msgEmail || "";
    return "";
  }

  function show(input, text) {
    var label = input.closest("label");
    var msg = label.querySelector(".field-msg");
    if (!text) {
      if (msg) msg.remove();
      label.classList.remove("has-error");
      input.removeAttribute("aria-invalid");
      return;
    }
    if (!msg) {
      msg = document.createElement("span");
      msg.className = "field-msg";
      msg.setAttribute("role", "alert");
      label.appendChild(msg);
    }
    msg.textContent = text;
    label.classList.add("has-error");
    input.setAttribute("aria-invalid", "true");
  }

  // Checks all required fields, shows messages, focuses the first bad one. True if all fine.
  function validate(form) {
    var first = null;
    form.querySelectorAll("input[required]").forEach(function (input) {
      var text = problem(input);
      show(input, text);
      if (text && !first) first = input;
    });
    if (first) first.focus();
    return !first;
  }

  function clear(form) {
    form.querySelectorAll("input").forEach(function (input) {
      if (input.closest("label")) show(input, "");
    });
  }

  // "Back" goes where you came from (Janis, 17.11.2026: from a project to /admin and back into the project, with its
  // view such as #manager). Every page with no back link of this kind notes itself; a link marked data-back-last
  // goes to the last noted page. A convenience: without storage it stays the link's own address.
  var backLink = document.querySelector("a[data-back-last]");
  function note() { try { sessionStorage.setItem("lastPage", location.pathname + location.search + location.hash); } catch (e) {} }
  if (!backLink) { note(); window.addEventListener("hashchange", note); }
  else {
    try {
      var last = sessionStorage.getItem("lastPage");
      if (last && last.charAt(0) === "/" && last.charAt(1) !== "/") backLink.setAttribute("href", last);
    } catch (e) {}
  }

  // Codes, tokens and commands copy with one click (Janis, 21.11.2026): the copy button beside them (ui.copy_button),
  // in a .copy-click box also the text itself. The button says "copied" in place for a moment. Without the clipboard
  // (an old browser, no permission) the text is selected, ready for Cmd+C.
  function copyButton() {
    var tpl = document.getElementById("copy-tpl");
    return tpl ? tpl.content.firstElementChild.cloneNode(true) : document.createElement("span");
  }
  function copyFrom(box) {
    var text = box.querySelector("[data-copy-text]");
    var button = box.querySelector("[data-copy]");
    if (!text) return;
    function select() {
      var range = document.createRange();
      range.selectNodeContents(text);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    function done() {
      if (!button) return;
      var label = button.dataset.label || button.getAttribute("aria-label");
      button.dataset.label = label;
      button.classList.add("copied");
      button.setAttribute("aria-label", button.dataset.done);
      button.dataset.tip = button.dataset.done;
      clearTimeout(button.copyTimer);
      button.copyTimer = setTimeout(function () {
        button.classList.remove("copied");
        button.setAttribute("aria-label", label);
        button.dataset.tip = label;
      }, 1600);
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text.textContent).then(done, select);
    else select();
  }
  document.addEventListener("click", function (event) {
    var box = event.target.closest(".copy-box");
    if (!box) return;
    if (event.target.closest("[data-copy]") || (box.classList.contains("copy-click") && event.target.closest("[data-copy-text]"))) {
      copyFrom(box);
    }
  });

  window.AgentHub = Object.assign(window.AgentHub || {}, { validate: validate, clear: clear, reload: reload, swap: swap, act: act, live: live, hold: hold, copyButton: copyButton });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("novalidate")) return;
    if (!validate(form)) event.preventDefault();
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("label.has-error input")) show(event.target, "");
  });

  // "More AIs": the arrow in the Claude block of the drawer opens or closes the list of the other services.
  // On the document, so it still works after the rows were swapped (ailink.js, "use as standard").
  // It glides (Janis, 22.11.2026: the tiles jumped apart and together): the first AI's block grows to its tools and
  // usage, the list grows out of nothing, both with the spring and interruptible; closed, the list is hidden again.
  var aiSprings = [];
  function glideHeight(el, from, to, done) {
    var finish = function () { el.style.height = ""; el.style.overflow = ""; if (done) done(); };
    if (!window.Motion || Motion.reduced() || Math.abs(from - to) < 1) { finish(); return; }
    el.style.overflow = "hidden";
    el.style.height = from + "px";
    var s = Motion.spring(from, Motion.MOVE, function (v) {
      el.style.height = Math.max(0, v) + "px";
      if (!s.active && v === to) finish();
    }, 0.5);
    aiSprings.push(s);
    s.to(to);
  }
  // All AI tiles are as high as the highest one (Janis, 23.11.2026): with the list open, every tile gets the height of the
  // highest as its minimum (--tile-h on the panel, app.css); folded, the top tile stays compact. Measured with the
  // minimum taken away, so a tile that got smaller (shorter text, another language) shrinks the others again.
  function equalizeTiles() {
    var panel = document.getElementById("settings-panel"), more = document.getElementById("ai-more");
    if (!panel) return;
    panel.style.removeProperty("--tile-h");
    if (!more || more.hidden) return;
    var tallest = 0;
    panel.querySelectorAll("#ai-services .service").forEach(function (tile) {
      tallest = Math.max(tallest, tile.getBoundingClientRect().height);
    });
    if (tallest) panel.style.setProperty("--tile-h", Math.ceil(tallest) + "px");
  }
  window.AgentHub = window.AgentHub || {};
  window.AgentHub.equalizeTiles = equalizeTiles;
  window.addEventListener("resize", equalizeTiles);

  document.addEventListener("click", function (event) {
    var aiToggle = event.target.closest("#ai-toggle");
    var aiMore = document.getElementById("ai-more");
    if (!aiToggle || !aiMore) return;
    var first = aiToggle.closest(".service") || aiToggle.parentElement;
    var open = aiToggle.getAttribute("aria-expanded") !== "true";
    aiSprings.forEach(function (s) { s.stop(); });   // a click during the glide turns it around from where it is
    aiSprings = [];
    var fromFirst = first.getBoundingClientRect().height;
    var fromMore = aiMore.hidden ? 0 : aiMore.getBoundingClientRect().height;
    [first, aiMore].forEach(function (el) { el.style.height = ""; el.style.overflow = ""; });
    aiMore.hidden = false;
    aiToggle.setAttribute("aria-expanded", String(open));
    equalizeTiles();
    var toFirst = first.getBoundingClientRect().height;
    var toMore = open ? aiMore.getBoundingClientRect().height : 0;
    glideHeight(first, fromFirst, toFirst);
    glideHeight(aiMore, fromMore, toMore, open ? null : function () { aiMore.hidden = true; });
  });

  // Fold the list of the other AIs at once, no glide: it is called while the drawer is still out of sight.
  function foldAis() {
    var more = document.getElementById("ai-more"), arrow = document.getElementById("ai-toggle");
    if (!more || !arrow || more.hidden) return;
    aiSprings.forEach(function (s) { s.stop(); });
    aiSprings = [];
    var first = arrow.closest(".service") || arrow.parentElement;
    [first, more].forEach(function (el) { el.style.height = ""; el.style.overflow = ""; });
    more.hidden = true;
    arrow.setAttribute("aria-expanded", "false");
  }

  // Settings drawer: slides out of the top right corner, the handle rides along.
  var drawer = document.getElementById("settings");
  var toggle = document.getElementById("settings-toggle");
  if (drawer && toggle) {
    var setOpen = function (open) {
      if (open) foldAis();   // the list of the other AIs always starts folded (Janis, 23.11.2026)
      drawer.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    var isOpen = function () { return drawer.classList.contains("open"); };
    toggle.addEventListener("click", function () { setOpen(!isOpen()); });
    document.addEventListener("click", function (event) {
      if (isOpen() && !event.target.closest("#settings")) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) setOpen(false);
    });
  }

  // Select: the browser's popup cannot be styled, so a select inside .has-select gets its own
  // list. The select stays in the page as the form field and keeps the value.
  document.querySelectorAll(".has-select select").forEach(function (select) {
    var menu = document.createElement("ul");
    menu.className = "select-menu";
    menu.setAttribute("role", "listbox");
    var items = [];
    // The entries follow the options; built again when a script swapped the options (the model picker after a change
    // of the AI, picker.js sends "agenthub:options").
    function build() {
      menu.textContent = "";
      items = Array.prototype.map.call(select.options, function (option) {
        var item = document.createElement("li");
        item.className = "select-option";
        item.setAttribute("role", "option");
        item.textContent = option.textContent;
        item.dataset.value = option.value;
        menu.appendChild(item);
        return item;
      });
    }
    build();
    select.addEventListener("agenthub:options", build);
    select.parentNode.appendChild(menu);
    select.setAttribute("aria-haspopup", "listbox");

    var active = -1;
    function mark(index) {
      active = index;
      items.forEach(function (item, i) { item.classList.toggle("active", i === index); });
    }
    function isOpen() { return menu.classList.contains("open"); }
    // An option can be hidden (the effort levels a model does not have, picker.js): its entry is hidden, too,
    // and the arrow keys skip it.
    function step(from, by) {
      for (var i = from + by; i >= 0 && i < items.length; i += by) if (!items[i].hidden) return i;
      return from;
    }
    function open() {
      items.forEach(function (item, i) {
        item.hidden = select.options[i].hidden;
        item.setAttribute("aria-selected", String(i === select.selectedIndex));
      });
      mark(select.selectedIndex);
      float();
      menu.classList.add("open");
      select.parentNode.classList.add("open");   // turns the arrow
      select.setAttribute("aria-expanded", "true");
    }
    // Outside a dialog the list floats in its own holder under <body> while it is open (Janis, 21.11.2026): a tile
    // that clips (the manager chat pulled small) or lies below its neighbour can not cut it off. It opens below the
    // box, or above when there is more room there, and is never taller than the room it has. A dialog is in the
    // browser's top layer, so a list in a dialog stays where it is.
    var holder = null;
    function float() {
      if (select.closest("dialog")) return;
      var style = getComputedStyle(menu);
      var minWidth = parseFloat(style.minWidth) || 0, rightAligned = style.left === "auto";
      if (!holder) {
        holder = document.createElement("div");
        holder.className = box.className.replace(/\bopen\b/, "") + " select-float";
        document.body.appendChild(holder);
      }
      if (menu.parentNode !== holder) holder.appendChild(menu);
      var rect = box.getBoundingClientRect(), gap = 6, edge = 8;
      var width = Math.max(rect.width + 2, minWidth);
      var left = rightAligned ? rect.right + 1 - width : rect.left - 1;
      left = Math.max(edge, Math.min(left, window.innerWidth - edge - width));
      menu.style.maxHeight = "";
      var wanted = Math.min(menu.scrollHeight, parseFloat(getComputedStyle(menu).maxHeight) || menu.scrollHeight);
      var below = window.innerHeight - rect.bottom - gap - edge, above = rect.top - gap - edge;
      var up = wanted > below && above > below;
      var room = up ? above : below;
      menu.style.left = left + "px";
      menu.style.right = "auto";
      menu.style.width = width + "px";
      menu.style.maxHeight = Math.max(120, Math.min(wanted, room)) + "px";
      menu.style.top = up ? Math.max(edge, rect.top - gap - Math.min(wanted, room)) + "px" : rect.bottom + gap + "px";
      menu.style.transformOrigin = up ? "bottom center" : "top center";
    }
    window.addEventListener("resize", function () { if (isOpen()) close(); });
    window.addEventListener("scroll", function (event) {   // the page or a scrolling tile moved the box away
      if (isOpen() && !menu.contains(event.target)) close();
    }, true);

    // Opened with mouse or finger, the focus goes again when the list closes (Janis, 14.11.2026: the glow of the
    // focus stayed on the capsule after closing). With the keyboard the focus stays, as it should.
    var byPointer = false;
    function close() {
      menu.classList.remove("open");
      select.parentNode.classList.remove("open");
      select.setAttribute("aria-expanded", "false");
      if (byPointer && document.activeElement === select) select.blur();
    }
    function choose(index) {
      if (index !== select.selectedIndex) {
        select.selectedIndex = index;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      close();
      if (!byPointer && (document.activeElement === select || !touched)) select.focus({ preventScroll: true });
    }
    var touched = false;   // the last pointer was a finger: never focus the select (see below)
    menu.addEventListener("pointerdown", function (event) { touched = event.pointerType === "touch"; });

    // The whole block opens the list, not only the line with the value: the arrow, the small label and the
    // padding count too (Janis, 11.11.2026: same click area as the arrow of the AI list).
    // The select itself takes no pointer at all (app.css: pointer-events: none): iPhone Safari opened its own
    // picker on a tap, which preventDefault on mousedown cannot stop (Janis, 14.11.2026). The block takes the
    // tap instead; its click is cancelled too, so the label never hands the tap on to the select. On a touch
    // screen the select is not focused either, so no system picker can come up; keyboards still use it.
    var box = select.parentNode;
    box.addEventListener("pointerdown", function (event) {
      if (menu.contains(event.target)) return;
      event.preventDefault();
      byPointer = true;
      if (event.pointerType !== "touch") select.focus({ preventScroll: true });
      if (isOpen()) close(); else open();
    });
    box.addEventListener("click", function (event) { event.preventDefault(); });   // also for taps in the list
    select.addEventListener("keydown", function (event) {
      var key = event.key;
      byPointer = false;
      if (!isOpen()) {
        if (key === " " || key === "Enter" || (event.altKey && key === "ArrowDown")) { event.preventDefault(); open(); }
        return;
      }
      event.preventDefault();
      event.stopPropagation(); // Escape closes only the list, not the drawer
      if (key === "ArrowDown") mark(step(active, 1));
      else if (key === "ArrowUp") mark(step(active, -1));
      else if (key === "Enter" || key === " ") choose(active);
      else if (key === "Escape" || key === "Tab") close();
    });
    menu.addEventListener("mousedown", function (event) { event.preventDefault(); }); // keep focus on the select
    menu.addEventListener("click", function (event) {
      var item = event.target.closest(".select-option");
      if (item) choose(items.indexOf(item));
    });
    menu.addEventListener("pointermove", function (event) {
      var item = event.target.closest(".select-option");
      if (item) mark(items.indexOf(item));
    });
    document.addEventListener("click", function (event) {
      if (isOpen() && !event.target.closest(".has-select")) close();
    });
    select.addEventListener("blur", function () { setTimeout(function () { if (!menu.contains(document.activeElement)) close(); }, 0); });
  });

  // Dialogs: every [data-close] button closes the dialog it is in.
  document.addEventListener("click", function (event) {
    var close = event.target.closest("[data-close]");
    if (close) close.closest("dialog").close();
  });

  // Tooltips: the browser would show every title="..." in its own plain grey box. We take the text over
  // (icon-only buttons keep it as their aria-label), and show a small glass label of our own next to the
  // element after a short moment (at once when it is reached by keyboard).
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  var tipTimer = null;
  var tipFor = null;

  function adopt(el) {
    var text = el.getAttribute("title");
    if (text === null) return;
    el.removeAttribute("title");
    if (!text.trim()) return;
    el.dataset.tip = text;
    if (!el.hasAttribute("aria-label") && !el.textContent.trim()) el.setAttribute("aria-label", text);
  }
  Array.prototype.forEach.call(document.querySelectorAll("[title]"), adopt);

  function hideTip() {
    clearTimeout(tipTimer);
    tipTimer = null;
    tipFor = null;
    tip.classList.remove("show");
  }

  function showTip(el) {
    // Inside an open modal dialog the tip must live in that dialog: the dialog sits in the top layer above the page,
    // so a tip in <body> would be hidden behind it (17.11.2026: no "i" of the device window showed anything).
    var home = el.closest("dialog[open]") || document.body;
    if (tip.parentNode !== home) home.appendChild(tip);
    tip.textContent = el.dataset.tip;
    tip.classList.toggle("wide", el.classList.contains("info-dot"));   // an explanation, not a label
    tip.style.left = "0px";
    tip.style.top = "0px";
    var origin = tip.getBoundingClientRect();   // a dialog with a transform moves the origin of position: fixed
    var ox = origin.left, oy = origin.top;
    var r = el.getBoundingClientRect();
    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var below = r.bottom + 10 + h <= window.innerHeight - 8;
    tip.style.setProperty("--tip-from", below ? "4px" : "-4px");
    tip.style.left = Math.round(x - ox) + "px";
    tip.style.top = Math.round((below ? r.bottom + 10 : r.top - h - 10) - oy) + "px";
    tip.classList.add("show");
  }

  document.addEventListener("mouseover", function (event) {
    var el = event.target.closest ? event.target.closest("[title],[data-tip]") : null;
    if (el) adopt(el);
    if (!el || !el.dataset.tip) { hideTip(); return; }
    if (el === tipFor) return;
    hideTip();
    tipFor = el;
    tipTimer = setTimeout(function () { showTip(el); }, 350);
  });
  document.documentElement.addEventListener("mouseleave", hideTip);
  document.addEventListener("pointerdown", hideTip, true);
  document.addEventListener("scroll", hideTip, true);
  document.addEventListener("keydown", hideTip, true);
  document.addEventListener("focusin", function (event) {
    var el = event.target.closest ? event.target.closest("[data-tip]") : null;
    if (el && el.matches(":focus-visible")) { hideTip(); tipFor = el; showTip(el); }
  });
  document.addEventListener("focusout", hideTip);
  // An "i" (.info-dot) also shows its tip on a click or tap, for touch screens and for reading at leisure.
  document.addEventListener("click", function (event) {
    var el = event.target.closest ? event.target.closest(".info-dot[data-tip]") : null;
    if (!el) return;
    event.preventDefault();
    hideTip();
    tipFor = el;
    showTip(el);
  });
})();
