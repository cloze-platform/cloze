// The side panel on the exercise page: the chat's Guide and the Notebook, as
// tabs when the chat has both. On a computer it sits beside the chat and stays
// open or closed, on the tab you last used; on a phone it's a sheet from the
// bottom, closed with Close, the backdrop or Escape. Anything with
// data-panel-open="guide" or "notebook" opens it on that tab, or closes it if
// it's already open there. Without JavaScript, the Notebook toggle is a link
// to the Notebook page.
(function () {
  var panel = document.getElementById("panel");
  var backdrop = document.getElementById("panel-backdrop");
  if (!panel) return;

  var openers = Array.prototype.slice.call(document.querySelectorAll("[data-panel-open]"));
  var tabs = Array.prototype.slice.call(panel.querySelectorAll("[data-tab]"));
  var panes = Array.prototype.slice.call(panel.querySelectorAll("[data-pane]"));
  var names = panes.map(function (p) { return p.getAttribute("data-pane"); });
  var wide = window.matchMedia("(min-width: 1024px)");
  var OPEN_KEY = "cloze.panel", TAB_KEY = "cloze.panelTab";
  var current = names[0];
  var lastOpener = null;

  // Remembering the panel is a nicety: storage can be unavailable (private
  // browsing, blocked) without breaking the page.
  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* not remembered */ }
  }
  function recall(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  openers.forEach(function (opener) {
    opener.setAttribute("role", "button");
    opener.setAttribute("aria-expanded", "false");
  });

  // Guides are Markdown with images from the study's media library, rendered
  // with their own sanitiser (renderGuideMarkdown in static/js/shared.js).
  panel.querySelectorAll("[data-guide-md]").forEach(function (el) {
    if (typeof renderGuideMarkdown !== "function") return;
    el.innerHTML = renderGuideMarkdown(el.textContent);
    el.setAttribute("data-guide-done", "");
  });

  function isOpen() { return !panel.classList.contains("hidden"); }

  function sync() {
    openers.forEach(function (opener) {
      opener.setAttribute("aria-expanded", String(isOpen() && opener.getAttribute("data-panel-open") === current));
    });
  }

  function show(name) {
    if (names.indexOf(name) < 0) name = names[0];
    current = name;
    panes.forEach(function (pane) { pane.classList.toggle("hidden", pane.getAttribute("data-pane") !== name); });
    tabs.forEach(function (tab) {
      var on = tab.getAttribute("data-tab") === name;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
    });
    if (wide.matches) remember(TAB_KEY, name);
    sync();
  }

  function open(name, focus) {
    show(name || current);
    panel.classList.remove("hidden");
    panel.classList.add("flex");
    if (!wide.matches) {
      backdrop.classList.remove("hidden");
      document.body.style.overflow = "hidden";
    }
    if (focus) panel.focus();
    if (wide.matches) remember(OPEN_KEY, "open");
    sync();
  }

  function close(returnFocus) {
    panel.classList.add("hidden");
    panel.classList.remove("flex");
    backdrop.classList.add("hidden");
    document.body.style.overflow = "";
    if (wide.matches) remember(OPEN_KEY, "closed");
    sync();
    if (returnFocus && lastOpener) lastOpener.focus();
  }

  openers.forEach(function (opener) {
    opener.addEventListener("click", function (event) {
      event.preventDefault();
      lastOpener = opener;
      var name = opener.getAttribute("data-panel-open");
      isOpen() && current === name ? close(false) : open(name, !wide.matches);
    });
  });

  // Tabs: click, or the arrow keys to move between them.
  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { show(tab.getAttribute("data-tab")); });
    tab.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      var next = tabs[(i + step + tabs.length) % tabs.length];
      show(next.getAttribute("data-tab"));
      next.focus();
    });
  });

  panel.querySelector("[data-panel-close]").addEventListener("click", function () { close(true); });
  backdrop.addEventListener("click", function () { close(true); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen() && !wide.matches) close(true);
  });
  // Turning a phone sideways into computer width: drop the sheet's backdrop.
  wide.addEventListener("change", function () {
    backdrop.classList.add("hidden");
    document.body.style.overflow = "";
  });

  // How the page starts: a guide set to open at the start opens the first
  // time this chat is visited; otherwise a computer reopens the panel as it
  // was left.
  var startGuide = panel.getAttribute("data-open-guide");
  var seenKey = startGuide ? "cloze.guideSeen." + startGuide : null;
  if (seenKey && !recall(seenKey)) {
    remember(seenKey, "1");
    open("guide", false);
  } else if (wide.matches && recall(OPEN_KEY) === "open") {
    open(recall(TAB_KEY), false);
  } else {
    show(recall(TAB_KEY) || names[0]);
  }

  // ── Adding a line saved from the chat (select-save.js) ──
  // One more saved line, in every count on the page (the menu's too).
  function countOneMore() {
    document.querySelectorAll("[data-notebook-count]").forEach(function (el) {
      el.textContent = (parseInt(el.textContent, 10) || 0) + 1;
    });
  }

  window.ParticipantPanel = {
    isOpen: isOpen,
    open: function (name) { open(name || "notebook", !wide.matches); },
    addLine: function (text, title, speaker) {
      var list = document.getElementById("notebook-list");
      if (!list) return;
      var item = document.createElement("li");
      item.className = "flex flex-col gap-1.5 border-t border-p-line py-4";
      var quote = document.createElement("p");
      quote.className = "text-base leading-relaxed";
      quote.textContent = "“" + text + "”";
      var meta = document.createElement("p");
      meta.className = "text-[13px] text-p-hint";
      meta.textContent = (speaker ? speaker + " · " : "") + title + " · Just now";
      item.appendChild(quote);
      item.appendChild(meta);
      list.insertBefore(item, list.firstChild);
      document.getElementById("notebook-empty").classList.add("hidden");
      countOneMore();
    },
  };
})();
