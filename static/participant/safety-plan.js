// The safety plan form. Saves the participant's four sections through
// PUT /api/safety-plan/patient-sections, then any new "things to avoid"
// through POST /api/safety-plan/anti-pattern, one each. Things to avoid
// already in the plan are shown, not sent again.
(function () {
  var form = document.getElementById("plan-form");
  if (!form) return;
  var view = document.getElementById("plan-view");
  var error = document.getElementById("plan-error");
  var isDraft = form.dataset.draft === "true";

  var SECTIONS = {
    warning_signs: { key: "sign", label: "warning signs" },
    coping_strategies: { key: "strategy", label: "things that help you cope" },
    support_network: { key: "person", label: "people you can reach" },
    reasons_for_living: { key: "reason", label: "reasons for living" },
  };
  var NUMBERS = ["severity", "effectiveness", "comfort_level"];

  // ── Showing the form for a change to an approved plan ──
  document.querySelectorAll("[data-edit-plan]").forEach(function (button) {
    button.addEventListener("click", function () {
      form.classList.remove("hidden");
      if (view) view.classList.add("hidden");
      button.closest("section").classList.add("hidden");
      var first = form.querySelector("input, select");
      if (first) first.focus();
    });
  });
  var cancel = form.querySelector("[data-cancel-edit]");
  if (cancel) cancel.addEventListener("click", function () { window.location.reload(); });

  // ── Adding and removing entries ──
  form.addEventListener("click", function (event) {
    var add = event.target.closest("[data-add-row]");
    if (add) {
      var section = add.closest("[data-section]");
      var rows = section.querySelector("[data-rows]");
      rows.appendChild(section.querySelector("template[data-new-row]").content.cloneNode(true));
      var last = rows.lastElementChild;
      last.querySelector("input").focus();
      return;
    }
    var remove = event.target.closest("[data-remove-row]");
    if (remove) {
      var row = remove.closest("[data-row]");
      var next = row.parentElement.closest("[data-section]").querySelector("[data-add-row]");
      row.remove();
      if (next) next.focus();
    }
  });

  function readRows(section) {
    var items = [];
    form.querySelectorAll('[data-section="' + section + '"] [data-rows] [data-row]').forEach(function (row) {
      var item = {};
      row.querySelectorAll("[data-field]").forEach(function (field) {
        var name = field.getAttribute("data-field");
        item[name] = NUMBERS.indexOf(name) >= 0 ? parseInt(field.value, 10) : field.value.trim();
      });
      items.push(item);
    });
    return items;
  }

  function collect() {
    var data = {};
    Object.keys(SECTIONS).forEach(function (section) {
      data[section] = readRows(section).filter(function (item) { return item[SECTIONS[section].key]; });
    });
    return data;
  }

  function showError(text) {
    error.textContent = text;
    error.classList.remove("hidden");
    error.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  async function save(send) {
    error.classList.add("hidden");
    var data = collect();
    if (send) {
      var missing = Object.keys(SECTIONS).filter(function (s) { return !data[s].length; })
        .map(function (s) { return SECTIONS[s].label; });
      if (missing.length) {
        showError("Add at least one entry for " + missing.join(", ") + " before you send your plan.");
        return;
      }
    }
    // A draft saved for later stays a draft; sending moves it to your care team.
    if (isDraft) data.submit = send;

    var buttons = form.querySelectorAll("button[type=submit], [data-save]");
    buttons.forEach(function (b) { b.disabled = true; });
    try {
      await Cloze.api("PUT", "/api/safety-plan/patient-sections", data);
      // Each new thing to avoid is posted once: its row goes as soon as it's
      // saved, so trying again after an error doesn't add it twice.
      var rows = form.querySelectorAll('[data-section="anti_patterns"] [data-rows] [data-row]');
      for (var i = 0; i < rows.length; i++) {
        var pattern = rows[i].querySelector('[data-field="pattern"]').value.trim();
        if (!pattern) continue;
        var reason = rows[i].querySelector('[data-field="reason"]').value.trim();
        await Cloze.api("POST", "/api/safety-plan/anti-pattern", { pattern: pattern, reason: reason });
        rows[i].remove();
      }
      window.location.reload();          // the page shows where the plan now stands
    } catch (e) {
      showError(e.message);
      buttons.forEach(function (b) { b.disabled = false; });
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    save(true);
  });
  var later = form.querySelector("[data-save]");
  if (later) later.addEventListener("click", function () { save(false); });
})();
