// The exercise page: Markdown replies, the Before you start step, and the
// window closing while the page is open. Sending lives in chat.js.
(function () {
  // Model replies arrive as plain text from the server and are rendered here,
  // through renderMarkdown (static/js/shared.js): Markdown, then DOMPurify
  // with the same allowlist as today's page. Without it they stay plain text.
  function renderReplies(root) {
    (root || document).querySelectorAll("[data-md]:not([data-md-done])").forEach(function (el) {
      if (typeof renderMarkdown !== "function") return;
      el.innerHTML = renderMarkdown(el.textContent);
      el.setAttribute("data-md-done", "");
    });
  }
  window.ParticipantExercise = { renderReplies: renderReplies };
  renderReplies();

  // Start at the latest message, or at the one a notebook line points to
  // ("See it in the chat": #m-<id>), highlighted for a moment.
  var linked = /^#m-\d+$/.test(location.hash) && document.getElementById(location.hash.slice(1));
  if (linked) {
    linked.scrollIntoView({ block: "center" });
    linked.style.transition = "background-color 2.4s ease-out";
    linked.style.backgroundColor = "var(--p-accent-soft)";
    setTimeout(function () { linked.style.backgroundColor = ""; }, 1200);
  } else if (document.querySelector("[data-message-id]")) {
    window.scrollTo(0, document.body.scrollHeight);
  }

  // ── Before you start ──
  var form = document.getElementById("agree-form");
  if (form) {
    var check = document.getElementById("agree-check");
    var button = document.getElementById("agree-button");
    var hint = document.getElementById("agree-hint");
    var error = document.getElementById("agree-error");

    // A study's own text written as HTML: shown only once DOMPurify has
    // cleaned it, as today. Otherwise the built-in text stays.
    var text = document.getElementById("safety-text");
    // Text and links only: no ids, styles, forms, images or dialogs, so the
    // text can't restyle or stand in for Get help now. (An old custom text may
    // carry its own checkbox; the form below has one.)
    if (text && text.dataset.customHtml && typeof DOMPurify !== "undefined") {
      text.innerHTML = DOMPurify.sanitize(text.dataset.customHtml, {
        ALLOWED_TAGS: ["p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "h2", "h3", "h4", "a", "div", "span"],
        ALLOWED_ATTR: ["href"],
        ALLOW_DATA_ATTR: false,
      });
    }

    check.addEventListener("change", function () {
      button.disabled = !check.checked;
      hint.hidden = check.checked;
    });

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!check.checked) return;
      button.disabled = true;
      error.classList.add("hidden");
      try {
        var id = form.dataset.conversationId;
        if (!id) {
          var started = await Cloze.api("POST", "/api/windows/start_conversation", { template_id: Number(form.dataset.templateId) });
          id = started.conversation_id;
        }
        await Cloze.api("POST", "/api/conversation/" + id + "/consent", {});
        window.location.assign("/exercise/" + id);
      } catch (e) {
        error.textContent = e.message || "Something went wrong. Please try again.";
        error.classList.remove("hidden");
        button.disabled = false;
      }
    });
  }

  // ── The window closing while the page is open: reload, and the server
  // shows the exercise as finished. ──
  var closes = document.querySelector("[data-closes-at]");
  if (closes) {
    var wait = Number(closes.getAttribute("data-closes-at")) * 1000 - Date.now();
    if (wait > 0 && wait < 2147483647) setTimeout(function () { window.location.reload(); }, wait + 1500);
  }
})();
