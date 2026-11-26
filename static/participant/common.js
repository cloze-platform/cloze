// Shared by the participant pages; participant/base.html loads it before
// each page's own script.
(function () {
  // A JSON request to the app's API. Resolves with the response's JSON.
  // Rejects with an Error whose message is the server's error, or a general
  // one, plus .status (0 when the request never reached the server) and
  // .data (the response's JSON, if any).
  async function api(method, url, body) {
    var response;
    try {
      response = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw failure("Couldn't reach Cloze. Check your connection and try again.", 0, {});
    }
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw failure(data.error || "That didn't work. Please try again.", response.status, data);
    return data;
  }

  function failure(message, status, data) {
    var error = new Error(message);
    error.status = status;
    error.data = data;
    return error;
  }

  // Tell screen readers through the page's polite live region. It's cleared
  // first, so the same message twice is read twice.
  function announce(text) {
    var region = document.getElementById("announcer");
    if (!region) return;
    region.textContent = "";
    setTimeout(function () { region.textContent = text; }, 50);
  }

  window.Cloze = { api: api, announce: announce };
})();
