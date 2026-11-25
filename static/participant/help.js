// Get help now: links marked data-help-open open the help dialog in place.
// Without JavaScript, or without <dialog> support, they go to /help instead.
(function () {
  var dialog = document.getElementById("help-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-help-open]");
    if (opener) {
      event.preventDefault();
      dialog.showModal();
      return;
    }
    // Close on the Close button, or a click on the backdrop around the sheet.
    if (event.target.closest("[data-help-close]") || event.target === dialog) {
      dialog.close();
    }
  });
})();
