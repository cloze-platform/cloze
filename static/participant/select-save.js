// Select text in the chat, then "Save to notebook". Saves through today's
// POST /api/save_selection with the ids of the messages the selection covers.
(function () {
  var chat = document.querySelector("[data-save-to]");
  var bar = document.getElementById("save-bar");
  var button = document.getElementById("save-button");
  var announcer = document.getElementById("announcer");
  if (!chat || !bar || !button) return;
  var label = button.querySelector("span");

  var conversationId = Number(chat.getAttribute("data-save-to"));
  var title = (document.querySelector("main h1") || {}).textContent || "";
  var touch = window.matchMedia("(pointer: coarse)").matches;
  var current = null;          // { text, messageIds }
  var timer = null;

  function hide() {
    bar.classList.add("hidden");
    current = null;
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
    return { text: text, messageIds: ids, rect: range.getBoundingClientRect() };
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
  window.addEventListener("scroll", function () {
    if (!current || button.disabled) return;
    var found = selectedInChat();
    found ? place(found.rect) : hide();
  }, { passive: true });

  // Keep the selection when the button is pressed.
  button.addEventListener("mousedown", function (event) { event.preventDefault(); });

  button.addEventListener("click", async function () {
    if (!current) return;
    var saving = current;
    button.disabled = true;
    try {
      var response = await fetch("/api/save_selection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, text: saving.text, message_ids: saving.messageIds }),
      });
      if (!response.ok) throw new Error();
      if (window.ParticipantPanel) window.ParticipantPanel.addLine(saving.text, title);
      announcer.textContent = "Saved to your notebook.";
      label.textContent = "Saved";
      setTimeout(function () {
        window.getSelection().removeAllRanges();
        hide();
        label.textContent = "Save to notebook";
        button.disabled = false;
      }, 900);
    } catch (e) {
      announcer.textContent = "That line wasn't saved. Please try again.";
      label.textContent = "Not saved. Try again";
      button.disabled = false;
    }
  });
})();
