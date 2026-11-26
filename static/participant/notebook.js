// The Notebook page: add, edit or clear the note on a saved line
// (PUT /api/selections/<id>), and remove a line (DELETE /api/selections/<id>).
(function () {
  function request(method, id, body) {
    return Cloze.api(method, "/api/selections/" + id, body);
  }

  function parts(line) {
    return {
      id: line.getAttribute("data-line"),
      view: line.querySelector("[data-note-view]"),
      text: line.querySelector("[data-note-text]"),
      form: line.querySelector("[data-note-form]"),
      input: line.querySelector("[data-note-input]"),
      edit: line.querySelector("[data-note-edit]"),
      error: line.querySelector("[data-line-error]"),
    };
  }

  function showForm(p, show) {
    p.form.classList.toggle("hidden", !show);
    p.form.classList.toggle("flex", show);
    p.edit.hidden = show;
    if (show) {
      p.input.value = p.text.textContent;
      p.input.focus();
    }
  }

  document.addEventListener("click", function (event) {
    var line = event.target.closest("[data-line]");
    if (!line) return;
    var p = parts(line);
    if (event.target.closest("[data-note-edit]")) showForm(p, true);
    if (event.target.closest("[data-note-cancel]")) { showForm(p, false); p.edit.focus(); }
    var remove = event.target.closest("[data-remove]");
    if (remove) {
      if (!window.confirm("Remove this line from your notebook?")) return;
      remove.disabled = true;
      request("DELETE", p.id).then(function () {
        var section = line.closest("section");
        line.remove();
        Cloze.announce("Removed from your notebook.");
        if (!section.querySelector("[data-line]")) section.remove();
      }).catch(function (e) {
        remove.disabled = false;
        p.error.textContent = e.message;
        p.error.classList.remove("hidden");
      });
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-note-form]");
    if (!form) return;
    event.preventDefault();
    var line = form.closest("[data-line]");
    var p = parts(line);
    var save = form.querySelector("button[type=submit]");
    if (save.disabled) return;
    save.disabled = true;
    p.error.classList.add("hidden");
    request("PUT", p.id, { note: p.input.value }).then(function (data) {
      save.disabled = false;
      var note = data.own_note || "";
      p.text.textContent = note;
      p.view.classList.toggle("hidden", !note);
      p.edit.textContent = note ? "Edit note" : "Add a note";
      showForm(p, false);
      p.edit.focus();
      Cloze.announce(note ? "Note saved." : "Note removed.");
    }).catch(function (e) {
      save.disabled = false;
      p.error.textContent = e.message;
      p.error.classList.remove("hidden");
    });
  });
})();
