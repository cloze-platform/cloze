// The side panel on the exercise page. On a computer it sits beside the chat
// and stays open or closed as you last left it; on a phone it's a sheet from
// the bottom, closed with Close, the backdrop or Escape. Without JavaScript,
// the toggle is a link to the Notebook page.
(function () {
  var panel = document.getElementById("panel");
  var toggle = document.getElementById("panel-toggle");
  var backdrop = document.getElementById("panel-backdrop");
  if (!panel || !toggle) return;

  var wide = window.matchMedia("(min-width: 1024px)");
  var KEY = "cloze.panel";
  toggle.setAttribute("role", "button");
  toggle.setAttribute("aria-expanded", "false");

  function isOpen() { return !panel.classList.contains("hidden"); }

  function open(focus) {
    panel.classList.remove("hidden");
    panel.classList.add("flex");
    toggle.setAttribute("aria-expanded", "true");
    if (!wide.matches) {
      backdrop.classList.remove("hidden");
      document.body.style.overflow = "hidden";
    }
    if (focus) panel.focus();
    if (wide.matches) localStorage.setItem(KEY, "open");
  }

  function close(returnFocus) {
    panel.classList.add("hidden");
    panel.classList.remove("flex");
    toggle.setAttribute("aria-expanded", "false");
    backdrop.classList.add("hidden");
    document.body.style.overflow = "";
    if (returnFocus) toggle.focus();
    if (wide.matches) localStorage.setItem(KEY, "closed");
  }

  toggle.addEventListener("click", function (event) {
    event.preventDefault();
    isOpen() ? close(false) : open(!wide.matches);
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

  if (wide.matches && localStorage.getItem(KEY) === "open") open(false);

  // ── Adding a line saved from the chat (select-save.js) ──
  function counts(n) {
    document.querySelectorAll("[data-notebook-count]").forEach(function (el) { el.textContent = n; });
  }

  window.ParticipantPanel = {
    isOpen: isOpen,
    open: function () { open(!wide.matches); },
    addLine: function (text, title) {
      var list = document.getElementById("notebook-list");
      var item = document.createElement("li");
      item.className = "flex flex-col gap-1.5 border-t border-p-line py-4";
      var quote = document.createElement("p");
      quote.className = "text-base leading-relaxed";
      quote.textContent = "“" + text + "”";
      var meta = document.createElement("p");
      meta.className = "text-[13px] text-p-hint";
      meta.textContent = title + " · Just now";
      item.appendChild(quote);
      item.appendChild(meta);
      list.insertBefore(item, list.firstChild);
      document.getElementById("notebook-empty").classList.add("hidden");
      counts(list.children.length);
    },
  };
})();
