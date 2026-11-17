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
  function swap(ids) {
    return fetch(location.pathname + location.search, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("swap");
      return response.text();
    }).then(function (html) {
      var fresh = new DOMParser().parseFromString(html, "text/html");
      ids.forEach(function (id) {
        var now = document.getElementById(id), next = fresh.getElementById(id);
        if (!now || !next) throw new Error("swap");
        now.innerHTML = next.innerHTML;
      });
    });
  }
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

  window.AgentHub = Object.assign(window.AgentHub || {}, { validate: validate, clear: clear, reload: reload, swap: swap, hold: hold });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute("novalidate")) return;
    if (!validate(form)) event.preventDefault();
  });

  document.addEventListener("input", function (event) {
    if (event.target.matches("label.has-error input")) show(event.target, "");
  });

  // "More AIs": the arrow in the Claude block of the drawer opens or closes the list of the other services.
  var aiToggle = document.getElementById("ai-toggle");
  var aiMore = document.getElementById("ai-more");
  if (aiToggle && aiMore) {
    aiToggle.addEventListener("click", function () {
      var open = aiMore.hidden;
      aiMore.hidden = !open;
      aiToggle.setAttribute("aria-expanded", String(open));
    });
  }

  // Settings drawer: slides out of the top right corner, the handle rides along.
  var drawer = document.getElementById("settings");
  var toggle = document.getElementById("settings-toggle");
  if (drawer && toggle) {
    var setOpen = function (open) {
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
    var items = Array.prototype.map.call(select.options, function (option) {
      var item = document.createElement("li");
      item.className = "select-option";
      item.setAttribute("role", "option");
      item.textContent = option.textContent;
      item.dataset.value = option.value;
      menu.appendChild(item);
      return item;
    });
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
      menu.classList.add("open");
      select.parentNode.classList.add("open");   // turns the arrow
      select.setAttribute("aria-expanded", "true");
    }
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
    tip.textContent = el.dataset.tip;
    tip.classList.toggle("wide", el.classList.contains("info-dot"));   // an explanation, not a label
    tip.style.left = "0px";
    tip.style.top = "0px";
    var r = el.getBoundingClientRect();
    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var below = r.bottom + 10 + h <= window.innerHeight - 8;
    tip.style.setProperty("--tip-from", below ? "4px" : "-4px");
    tip.style.left = Math.round(x) + "px";
    tip.style.top = Math.round(below ? r.bottom + 10 : r.top - h - 10) + "px";
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
