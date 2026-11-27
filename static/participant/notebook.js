// The notebook (templates/participant/notebook.html and notebook_page.html).
//
// Contents: a New mark on pages with lines saved since the participant last
// opened the notebook (remembered on this device), and search with filters,
// in the browser, over every entry.
//
// A page: the participant's thought on each line, saved when they leave the
// field (PUT /api/selections/<id>); "…" menus; Remove with a few seconds to
// Undo before the line is deleted (DELETE /api/selections/<id>).
(function () {
  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* not remembered */ }
  }
  function recall(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // ── Contents: New marks ──
  var SEEN_KEY = "cloze.notebookSeen";
  var cards = document.querySelectorAll("[data-page-card]");
  if (cards.length) {
    var seen = parseFloat(recall(SEEN_KEY));
    if (!isNaN(seen)) {
      cards.forEach(function (card) {
        if (parseFloat(card.getAttribute("data-latest")) > seen) card.querySelector("[data-new]").hidden = false;
      });
    }
    remember(SEEN_KEY, String(Date.now() / 1000));
  }

  // ── Contents: search and filters ──
  var area = document.querySelector("[data-search-area]");
  var dataEl = document.getElementById("notebook-data");
  if (area && dataEl) {
    var entries = JSON.parse(dataEl.textContent);
    var input = document.getElementById("nb-search");
    var chipsRow = area.querySelector("[data-chips]");
    var chips = Array.prototype.slice.call(area.querySelectorAll("[data-chip]"));
    var results = area.querySelector("[data-results]");
    var count = area.querySelector("[data-result-count]");
    var contents = document.querySelector("[data-contents]");
    var opener = document.querySelector("[data-search-open]");
    var closer = area.querySelector("[data-search-close]");
    var wide = window.matchMedia("(min-width: 1024px)");
    var chip = "all";
    var open = false;   // on a phone: the search screen is showing
    var WEEK = 7 * 86400;

    function fold(s) {
      return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    }
    entries.forEach(function (e) { e._text = fold(e.text + " " + e.thought + " " + e.page + " " + e.chapter); });

    function matches(e, words) {
      if (chip === "thoughts" && !e.thought) return false;
      if (chip === "week" && e.saved < Date.now() / 1000 - WEEK) return false;
      if (chip.indexOf("speaker:") === 0 && e.speaker !== chip.slice(8)) return false;
      return words.every(function (w) { return e._text.indexOf(w) !== -1; });
    }

    function result(e) {
      var item = el("li", "nb-paper flex flex-col gap-2 rounded-md px-4 py-3.5");
      var where = el("a", "self-start text-[13px] font-semibold text-p-accent-ink", e.chapter + " · " + e.page);
      where.href = e.url;
      item.appendChild(where);
      item.appendChild(el("blockquote", "nb-serif text-[17px] leading-relaxed text-p-ink", "“" + e.text + "”"));
      var meta = el("div", "flex flex-wrap items-center gap-x-2 text-[13px] text-p-paper-hint");
      if (e.speaker) meta.appendChild(el("span", "font-semibold text-p-ink-2", e.speaker));
      meta.appendChild(el("span", "", (e.speaker ? "· " : "") + e.date));
      var back = el("a", "font-semibold text-p-accent-ink", "See it in the chat ↗");
      back.href = e.chat_url;
      meta.appendChild(el("span", "", "·"));
      meta.appendChild(back);
      item.appendChild(meta);
      if (e.thought) item.appendChild(el("p", "text-base leading-relaxed text-p-pen", e.thought));
      return item;
    }

    function update() {
      var words = fold(input.value).split(/\s+/).filter(Boolean);
      var searching = words.length > 0 || chip !== "all";
      var showChips = wide.matches ? (searching || document.activeElement === input) : open;
      chipsRow.classList.toggle("hidden", !showChips);
      chipsRow.classList.toggle("flex", showChips);
      contents.hidden = searching || (!wide.matches && open);
      results.textContent = "";
      results.classList.toggle("hidden", !searching);
      results.classList.toggle("flex", searching);
      if (!searching) { count.textContent = ""; return; }
      var found = entries.filter(function (e) { return matches(e, words); });
      found.forEach(function (e) { results.appendChild(result(e)); });
      count.textContent = found.length ? found.length + (found.length === 1 ? " line" : " lines")
                                       : "Nothing matches. Try other words, or All.";
    }

    input.addEventListener("input", update);
    input.addEventListener("focus", update);
    input.addEventListener("blur", function () { setTimeout(update, 150); });
    chips.forEach(function (button) {
      button.addEventListener("click", function () {
        chip = button.getAttribute("data-chip");
        chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c === button)); });
        update();
      });
    });

    function setOpen(value) {
      open = value;
      area.classList.toggle("hidden", !open);
      area.classList.toggle("flex", open);
      if (opener) opener.setAttribute("aria-expanded", String(open));
      if (!open) {
        input.value = "";
        chip = "all";
        chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.getAttribute("data-chip") === "all")); });
      }
      update();
      if (open) input.focus(); else if (opener) opener.focus();
    }
    if (opener) opener.addEventListener("click", function () { setOpen(true); });
    if (closer) closer.addEventListener("click", function () { setOpen(false); });
    wide.addEventListener("change", update);
  }

  // ── A page: thoughts ──
  function grow(field) {
    field.style.height = "auto";
    field.style.height = field.scrollHeight + "px";
  }

  document.querySelectorAll("[data-entry]").forEach(function (entry) {
    var id = entry.getAttribute("data-entry");
    var field = entry.querySelector("[data-thought]");
    var status = entry.querySelector("[data-thought-status]");
    var saved = field.value;
    var timer = null;
    grow(field);

    async function save() {
      clearTimeout(timer);
      var value = field.value.trim();
      if (value === saved.trim()) return;
      status.textContent = "Saving…";
      try {
        await Cloze.api("PUT", "/api/selections/" + id, { note: value });
        saved = value;
        status.textContent = "Saved";
        setTimeout(function () { if (status.textContent === "Saved") status.textContent = ""; }, 2000);
      } catch (e) {
        status.textContent = (e.data && e.data.error) || "Not saved. Check your connection and try again.";
      }
    }
    field.addEventListener("input", function () {
      grow(field);
      clearTimeout(timer);
      timer = setTimeout(save, 1500);
    });
    field.addEventListener("blur", save);
  });

  // ── A page: "…" menus ──
  var menus = Array.prototype.slice.call(document.querySelectorAll("[data-menu]"));
  function closeMenus(except) {
    menus.forEach(function (button) {
      var list = document.getElementById(button.getAttribute("aria-controls"));
      if (button === except || !list) return;   // a removed line's menu is gone
      button.setAttribute("aria-expanded", "false");
      list.hidden = true;
    });
  }
  menus.forEach(function (button) {
    var list = document.getElementById(button.getAttribute("aria-controls"));
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var opening = list.hidden;
      closeMenus(button);
      list.hidden = !opening;
      button.setAttribute("aria-expanded", String(opening));
      if (opening) list.querySelector("[role=menuitem]").focus();
    });
    list.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { list.hidden = true; button.setAttribute("aria-expanded", "false"); button.focus(); }
    });
  });
  document.addEventListener("click", function () { closeMenus(null); });

  // ── A page: remove, with a few seconds to undo ──
  var toast = document.querySelector("[data-toast]");
  var pending = null;   // { entry, timer }
  var UNDO_MS = 5000;

  function deleteNow(id) {
    // keepalive: still sent if the participant leaves the page meanwhile.
    return fetch("/api/selections/" + id, {
      method: "DELETE", headers: { "Content-Type": "application/json" }, body: "{}", keepalive: true,
      credentials: "same-origin",
    });
  }
  function refreshCounts() {
    var left = document.querySelectorAll("[data-entry]:not([hidden])");
    var thoughts = Array.prototype.filter.call(left, function (e) { return e.querySelector("[data-thought]").value.trim(); }).length;
    var counts = document.querySelector("[data-page-counts]");
    if (counts) counts.textContent = left.length + (left.length === 1 ? " line" : " lines") +
      (thoughts ? " · " + thoughts + (thoughts === 1 ? " thought" : " thoughts") : "");
    var empty = document.querySelector("[data-page-empty]");
    if (empty) empty.hidden = left.length > 0;
  }
  function commit() {
    if (!pending) return;
    clearTimeout(pending.timer);
    deleteNow(pending.entry.getAttribute("data-entry"));
    pending.entry.remove();
    pending = null;
    toast.hidden = true;
    toast.classList.remove("flex");
  }
  document.querySelectorAll("[data-remove]").forEach(function (button) {
    button.addEventListener("click", function () {
      commit();
      var entry = button.closest("[data-entry]");
      closeMenus(null);
      entry.hidden = true;
      refreshCounts();
      pending = { entry: entry, timer: setTimeout(commit, UNDO_MS) };
      toast.hidden = false;
      toast.classList.add("flex");
      toast.querySelector("[data-undo]").focus();
      Cloze.announce("Removed from your notebook. Undo is available for a few seconds.");
    });
  });
  if (toast) {
    toast.querySelector("[data-undo]").addEventListener("click", function () {
      if (!pending) return;
      clearTimeout(pending.timer);
      pending.entry.hidden = false;
      refreshCounts();
      var focusTo = pending.entry.querySelector("[data-menu]");
      pending = null;
      toast.hidden = true;
      toast.classList.remove("flex");
      Cloze.announce("Put back.");
      if (focusTo) focusTo.focus();
    });
    window.addEventListener("pagehide", commit);
  }

  // ── A page: arriving at one line (from search) ──
  var target = location.hash && document.getElementById(location.hash.slice(1));
  if (target && target.hasAttribute("data-entry")) {
    target.scrollIntoView({ block: "center" });
    target.classList.add("nb-flash");
  }
})();
