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
  var conversationId = form.dataset.conversationId;
  var busy = false;

  var announce = Cloze.announce;

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
    var bubble = el("div", "max-w-[82%] whitespace-pre-wrap rounded-[20px] rounded-br-md bg-p-accent-soft px-4 py-2.5 text-base leading-relaxed", text);
    bubble.setAttribute("data-bubble", "");
    wrap.appendChild(bubble);
    var status = el("div", "flex flex-wrap items-center justify-end gap-x-3 gap-y-1 pr-1 text-xs text-p-hint");
    status.setAttribute("data-status", "");
    status.appendChild(el("time", "", now()));
    wrap.appendChild(status);
    list.appendChild(wrap);
    return wrap;
  }

  function render(root) {
    if (window.ParticipantExercise) window.ParticipantExercise.renderReplies(root);
  }

  // A speaker's part of a reply: the same markup as templates/participant/_speaker.html.
  function partNode(part) {
    var node = el("div", "flex flex-col gap-1.5");
    node.setAttribute("data-part", "");
    var sp = part.speaker;
    if (sp) {
      node.dataset.speaker = sp.name;
      var label = el("div", "flex items-center gap-2");
      label.setAttribute("data-speaker-label", "");
      if (sp.image_url) {
        var img = el("img", "h-7 w-7 shrink-0 rounded-full object-cover");
        img.src = sp.image_url;
        img.alt = "";
        label.appendChild(img);
      } else {
        var initial = el("span", "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-p-accent-soft text-xs font-semibold text-p-accent-ink", sp.initial);
        initial.setAttribute("aria-hidden", "true");
        label.appendChild(initial);
      }
      label.appendChild(el("span", "text-sm font-semibold text-p-ink", sp.name));
      if (sp.role) label.appendChild(el("span", "text-[13px] text-p-hint", sp.role));
      node.appendChild(label);
    }
    var body = el("div", "p-prose text-base leading-[1.65]", part.text);
    body.setAttribute("data-md", "");
    node.appendChild(body);
    return node;
  }

  // A reply. In a chat with a cast, its speakers' parts appear one after
  // another, like separate messages (together if the participant prefers
  // less motion). Returns how long until the last part is shown, in ms.
  var PART_GAP = 700;
  function addReply(data) {
    var parts = data.parts && data.parts.length ? data.parts : null;
    var wrap = el("div", parts ? "flex flex-col gap-4" : "flex flex-col gap-1");
    wrap.dataset.messageId = data.message_id;
    var time = el("time", "text-xs text-p-hint", now());
    if (!parts) {
      var body = el("div", "p-prose text-base leading-[1.65]", data.response);
      body.setAttribute("data-md", "");
      wrap.appendChild(body);
      wrap.appendChild(time);
      list.appendChild(wrap);
      render(wrap);
      announce("New reply.");
      return 0;
    }
    var gap = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : PART_GAP;
    wrap.appendChild(time);
    list.appendChild(wrap);
    parts.forEach(function (part, i) {
      function show() {
        wrap.insertBefore(partNode(part), time);
        render(wrap);
        announce(part.speaker ? "New reply from " + part.speaker.name + "." : "New reply.");
        if (i) scrollDown();
      }
      i && gap ? setTimeout(show, i * gap) : show();
    });
    return (parts.length - 1) * gap;
  }

  function showWaiting() {
    var wrap = el("div", "flex items-center gap-2.5 text-sm text-p-ink-3");
    wrap.id = "waiting";
    wrap.appendChild(el("span", "", form.dataset.writer ? form.dataset.writer + " is writing" : "Writing a reply"));
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

  // ── A message without a reply ──
  // retry: send it again with the same id (the server never saves it twice).
  // edit: put the text back in the reply box; only when it wasn't saved.
  // reload: show the page again, which says why replying stopped.
  function markFailed(wrap, text, reason, opts) {
    var status = wrap.querySelector("[data-status]");
    status.textContent = "";
    status.appendChild(el("span", "font-medium text-p-help", reason));
    function action(label, handler) {
      var button = el("button", "min-h-8 rounded-lg px-2 font-semibold text-p-accent-ink hover:bg-p-raised", label);
      button.type = "button";
      button.addEventListener("click", handler);
      status.appendChild(button);
    }
    if (opts.retry) action("Try again", function () { deliver(wrap, text, wrap.dataset.clientId); });
    if (opts.edit) {
      action("Edit", function () {
        wrap.remove();
        input.value = text;
        grow();
        input.focus();
      });
    }
    if (opts.reload) action("See why", function () { window.location.reload(); });
    announce(reason);
  }

  async function deliver(wrap, text, clientId) {
    if (busy) return;
    busy = true;
    send.disabled = true;
    var status = wrap.querySelector("[data-status]");
    status.textContent = "";
    status.appendChild(el("span", "", "Sending…"));
    showWaiting();
    scrollDown();

    var data, failed = null;
    try {
      data = await Cloze.api("POST", "/api/conversation/" + conversationId + "/message",
                             { message: text, client_message_id: clientId });
    } catch (e) {
      failed = e;
      data = e.data;
    }
    hideWaiting();
    busy = false;
    send.disabled = false;

    if (!failed) {
      status.textContent = "";
      status.appendChild(el("time", "", now()));
      wrap.dataset.messageId = data.user_message_id;
      delete wrap.dataset.pendingReply;
      var shownIn = addReply(data);
      updateTurns(data.turns_remaining);
      scrollDown();
      // The last turn ended the exercise: show it as finished, once the reply is all shown.
      if (data.ended) setTimeout(function () { window.location.reload(); }, 1200 + shownIn);
      return;
    }
    if (failed.status === 0) {
      markFailed(wrap, text, "Couldn't reach Cloze. Check your connection.", { retry: true, edit: true });
    } else if (data.saved) {
      // Saved on the server; only the reply is missing.
      wrap.dataset.messageId = data.user_message_id;
      markFailed(wrap, text, "Saved. The reply didn't come through.", { retry: true });
    } else if (data.in_progress) {
      markFailed(wrap, text, "Still sending. Wait a moment, then try again.", { retry: true });
    } else if (failed.status === 403 && (data.ended || data.turn_limit_reached)) {
      markFailed(wrap, text, "Not sent. " + (data.error || "This conversation has ended."), { reload: true });
    } else if (failed.status >= 500) {
      markFailed(wrap, text, "The reply didn't come through.", { retry: true, edit: true });
    } else {
      markFailed(wrap, text, "Not sent. " + (data.error || "Something went wrong."), { edit: true });
    }
  }

  // A message saved earlier whose reply never came (shown by the server).
  list.querySelectorAll("[data-pending-reply]").forEach(function (wrap) {
    var text = wrap.querySelector("[data-bubble]").textContent;
    wrap.querySelector("[data-retry]").addEventListener("click", function () {
      deliver(wrap, text, wrap.dataset.clientId);
    });
  });

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
