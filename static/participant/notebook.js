// The Notebook page: add, edit or clear the note on a saved line
// (PUT /api/selections/<id>), and remove a line (DELETE /api/selections/<id>).
(function () {
  var announcer = document.getElementById("announcer");

  function request(method, id, body) {
    return fetch("/api/selections/" + id, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) throw new Error(data.error || "That didn't save. Please try again.");
        return data;
      });
    });
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
    if (event.target.closest("[data-remove]")) {
      if (!window.confirm("Remove this line from your notebook?")) return;
      request("DELETE", p.id).then(function () {
        var section = line.closest("section");
        line.remove();
        announcer.textContent = "Removed from your notebook.";
        if (!section.querySelector("[data-line]")) section.remove();
      }).catch(function (e) {
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
    p.error.classList.add("hidden");
    request("PUT", p.id, { note: p.input.value }).then(function (data) {
      var note = data.own_note || "";
      p.text.textContent = note;
      p.view.classList.toggle("hidden", !note);
      p.edit.textContent = note ? "Edit note" : "Add a note";
      showForm(p, false);
      p.edit.focus();
      announcer.textContent = note ? "Note saved." : "Note removed.";
    }).catch(function (e) {
      p.error.textContent = e.message;
      p.error.classList.remove("hidden");
    });
  });
})();
