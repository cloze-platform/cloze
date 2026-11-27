// Select text in the chat, then "Save to notebook". Saves through today's
// POST /api/save_selection with the ids of the messages the selection covers.
(function () {
  var chat = document.querySelector("[data-save-to]");
  var bar = document.getElementById("save-bar");
  var button = document.getElementById("save-button");
  if (!chat || !bar || !button) return;
  var label = button.querySelector("span");

  var conversationId = Number(chat.getAttribute("data-save-to"));
  var title = (document.querySelector("main h1") || {}).textContent || "";
  var touch = window.matchMedia("(pointer: coarse)").matches;
  var current = null;          // { text, messageIds, speaker }
  var timer = null;

  function hide() {
    bar.classList.add("hidden");
    current = null;
  }

  // Whether the range covers any of node's text, not just its edge.
  function overlaps(range, node) {
    var whole = document.createRange();
    whole.selectNodeContents(node);
    var part = document.createRange();
    if (range.compareBoundaryPoints(Range.START_TO_START, whole) < 0) part.setStart(whole.startContainer, whole.startOffset);
    else part.setStart(range.startContainer, range.startOffset);
    if (range.compareBoundaryPoints(Range.END_TO_END, whole) > 0) part.setEnd(whole.endContainer, whole.endOffset);
    else part.setEnd(range.endContainer, range.endOffset);
    return !part.collapsed && part.toString().trim() !== "";
  }

  function selectedInChat() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return null;
    var range = selection.getRangeAt(0);
    if (!chat.contains(range.commonAncestorContainer)) return null;
    var text = selection.toString().replace(/\s+/g, " ").trim();
    if (text.length < 2) return null;
    var ids = [];
    chat.querySelectorAll("[data-message-id]").forEach(function (el) {
      if (range.intersectsNode(el)) ids.push(Number(el.getAttribute("data-message-id")));
    });
    if (!ids.length) return null;         // the greeting or the safety text, not a message
    // Who said it: when the selected text is all in one speaker's part (a
    // chat with a cast). A triple-click selection ends at the very start of
    // the next part, so count only parts whose text it actually covers.
    var speakers = [];
    chat.querySelectorAll("[data-part]").forEach(function (el) {
      if (range.intersectsNode(el) && overlaps(range, el)) speakers.push(el.getAttribute("data-speaker") || "");
    });
    var speaker = speakers.length && speakers.every(function (n) { return n && n === speakers[0]; }) ? speakers[0] : null;
    return { text: text, messageIds: ids, speaker: speaker, rect: range.getBoundingClientRect() };
  }

  function place(rect) {
    bar.classList.remove("hidden");
    var width = bar.offsetWidth, height = bar.offsetHeight;
    var left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
    // Above the selection; below it on touch screens, clear of the system menu.
    var top = touch || rect.top < height + 76 ? rect.bottom + 10 : rect.top - height - 10;
    bar.style.left = left + "px";
    bar.style.top = Math.min(top, window.innerHeight - height - 8) + "px";
  }

  document.addEventListener("selectionchange", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      if (button.disabled) return;          // saving: keep the bar until it's done
      var found = selectedInChat();
      if (!found) return hide();
      label.textContent = "Save to notebook";
      current = found;
      place(found.rect);
    }, 150);
  });
  // The bar is fixed to the window, so it follows the selection as the page scrolls.
  var queued = false;
  window.addEventListener("scroll", function () {
    if (!current || button.disabled || queued) return;
    queued = true;
    requestAnimationFrame(function () {         // once per frame, not per scroll event
      queued = false;
      var found = selectedInChat();
      found ? place(found.rect) : hide();
    });
  }, { passive: true });

  // Keep the selection when the button is pressed.
  button.addEventListener("mousedown", function (event) { event.preventDefault(); });

  button.addEventListener("click", async function () {
    if (!current) return;
    var saving = current;
    button.disabled = true;
    try {
      var body = { conversation_id: conversationId, text: saving.text, message_ids: saving.messageIds };
      if (saving.speaker) body.speaker_name = saving.speaker;
      await Cloze.api("POST", "/api/save_selection", body);
      if (window.ParticipantPanel) window.ParticipantPanel.addLine(saving.text, title, saving.speaker);
      Cloze.announce("Saved to your notebook.");
      label.textContent = "Saved";
      setTimeout(function () {
        window.getSelection().removeAllRanges();
        hide();
        label.textContent = "Save to notebook";
        button.disabled = false;
      }, 900);
    } catch (e) {
      Cloze.announce("That line wasn't saved. Please try again.");
      label.textContent = "Not saved. Try again";
      button.disabled = false;
    }
  });
})();
