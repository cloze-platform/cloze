// Sending on the exercise page. Each message gets an id (client_message_id),
// so a send can be tried again without ever being saved twice: the server
// returns the saved reply for an id it has seen. A message that couldn't be
// sent stays where it was written, with Try again and Edit.
(function () {
  var form = document.getElementById("composer");
  if (!form) return;
  var input = document.getElementById("reply");
  var send = document.getElementById("send");
  var list = document.getElementById("conversation");
  var announcer = document.getElementById("announcer");
  var conversationId = form.dataset.conversationId;
  var busy = false;

  function announce(text) {
    announcer.textContent = "";
    setTimeout(function () { announcer.textContent = text; }, 50);
  }

  function newId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "m-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
  }

  function now() {
    return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // ── The reply box grows with its text, up to its max height ──
  function grow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 192) + "px";
  }
  input.addEventListener("input", grow);

  // Enter sends; Shift+Enter starts a new line.
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  // ── Messages ──
  function addOwn(text, clientId) {
    var greeting = document.getElementById("greeting");
    if (greeting) greeting.remove();
    var wrap = el("div", "flex flex-col items-end gap-1");
    wrap.dataset.clientId = clientId;
    wrap.appendChild(el("div", "max-w-[82%] whitespace-pre-wrap rounded-[20px] rounded-br-md bg-p-accent-soft px-4 py-2.5 text-base leading-relaxed", text));
    var status = el("div", "flex flex-wrap items-center justify-end gap-x-3 gap-y-1 pr-1 text-xs text-p-hint");
    status.appendChild(el("time", "", now()));
    wrap.appendChild(status);
    list.appendChild(wrap);
    return wrap;
  }

  function addReply(text, messageId) {
    var wrap = el("div", "flex flex-col gap-1");
    wrap.dataset.messageId = messageId;
    var body = el("div", "p-prose text-base leading-[1.65]", text);
    body.setAttribute("data-md", "");
    wrap.appendChild(body);
    wrap.appendChild(el("time", "text-xs text-p-hint", now()));
    list.appendChild(wrap);
    if (window.ParticipantExercise) window.ParticipantExercise.renderReplies(wrap);
  }

  function showWaiting() {
    var wrap = el("div", "flex items-center gap-2.5 text-sm text-p-ink-3");
    wrap.id = "waiting";
    wrap.appendChild(el("span", "", "Writing a reply"));
    var dots = el("span", "flex gap-1");
    dots.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 3; i++) {
      var dot = el("span", "h-1.5 w-1.5 animate-pulse rounded-full bg-p-ring");
      dot.style.animationDelay = (i * 150) + "ms";
      dots.appendChild(dot);
    }
    wrap.appendChild(dots);
    list.appendChild(wrap);
  }

  function hideWaiting() {
    var waiting = document.getElementById("waiting");
    if (waiting) waiting.remove();
  }

  function scrollDown() {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }

  // ── Turns left ──
  function updateTurns(left) {
    if (left == null) return;
    var label = left + (left === 1 ? " turn" : " turns") + " left";
    var header = document.getElementById("turns-left");
    if (header) header.textContent = label;
    var notice = document.getElementById("few-turns");
    if (notice && left <= 5) {
      notice.querySelector("[data-few-turns-count]").textContent = label + " in this exercise.";
      notice.classList.remove("hidden");
      notice.classList.add("flex");
    }
  }

  // ── A message that couldn't be sent ──
  function markFailed(wrap, text, reason, canRetry) {
    var status = wrap.lastChild;
    status.textContent = "";
    var note = el("span", "font-medium text-p-help", "Not sent. " + reason);
    status.appendChild(note);
    if (canRetry) {
      var retry = el("button", "min-h-8 rounded-lg px-2 font-semibold text-p-accent-ink hover:bg-p-raised", "Try again");
      retry.type = "button";
      retry.addEventListener("click", function () { deliver(wrap, text, wrap.dataset.clientId); });
      status.appendChild(retry);
    }
    var edit = el("button", "min-h-8 rounded-lg px-2 font-semibold text-p-accent-ink hover:bg-p-raised", "Edit");
    edit.type = "button";
    edit.addEventListener("click", function () {
      wrap.remove();
      input.value = text;
      grow();
      input.focus();
    });
    status.appendChild(edit);
    announce("Your message wasn't sent. " + reason);
  }

  async function deliver(wrap, text, clientId) {
    if (busy) return;
    busy = true;
    send.disabled = true;
    var status = wrap.lastChild;
    status.textContent = "";
    status.appendChild(el("span", "", "Sending…"));
    showWaiting();
    scrollDown();

    var response, data;
    try {
      response = await fetch("/api/conversation/" + conversationId + "/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, client_message_id: clientId }),
      });
      data = await response.json().catch(function () { return {}; });
    } catch (e) {
      response = null;
    }
    hideWaiting();
    busy = false;
    send.disabled = false;

    if (response && response.ok) {
      status.textContent = "";
      status.appendChild(el("time", "", now()));
      wrap.dataset.messageId = data.user_message_id;
      addReply(data.response, data.message_id);
      announce("New reply.");
      updateTurns(data.turns_remaining);
      scrollDown();
      // The last turn ended the exercise: show it as finished.
      if (data.ended) setTimeout(function () { window.location.reload(); }, 1200);
      return;
    }
    if (!response) {
      markFailed(wrap, text, "Check your connection.", true);
    } else if (response.status === 403 && (data.ended || data.turn_limit_reached)) {
      window.location.reload();            // the server shows why it ended
    } else if (response.status === 502 || response.status >= 500) {
      markFailed(wrap, text, "The reply didn't come through.", true);
    } else {
      markFailed(wrap, text, data.error || "Something went wrong.", false);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    grow();
    var clientId = newId();
    deliver(addOwn(text, clientId), text, clientId);
  });
})();
