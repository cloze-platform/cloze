// Need help?: the study team's help with this exercise, in a dialog from the
// reply box. Its buttons send a message ("Star, help"), open the chat's guide,
// or go to a link. Get help now (help.js) is separate, for a crisis.
(function () {
  var dialog = document.getElementById("need-help-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var form = document.getElementById("composer");
  var reply = document.getElementById("reply");

  // Capture, so this dialog is closed before another opens (Get help now, the
  // guide) and its focus doesn't come back here.
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-need-help-open]")) {
      event.preventDefault();
      dialog.showModal();
      return;
    }
    if (!dialog.open) return;
    if (event.target === dialog || event.target.closest("[data-need-help-close], [data-need-help-dismiss]")) {
      dialog.close();
      return;
    }
    if (event.target.closest("[data-need-help-guide]")) {
      dialog.close();
      if (window.ParticipantPanel) window.ParticipantPanel.open("guide");
      return;
    }
    var send = event.target.closest("[data-need-help-send]");
    if (send && form && reply) {
      dialog.close();
      reply.value = send.getAttribute("data-need-help-send");
      reply.dispatchEvent(new Event("input", { bubbles: true }));
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else reply.focus();
    }
  }, true);
})();
