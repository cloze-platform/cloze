/* The Need help? editor, shared by Settings (the researcher's default) and
   Study Design (a chat's own). NeedHelpEditor.html(content, inputClass) gives
   the fields as HTML; NeedHelpEditor.read(root) gives back
   {heading, message, buttons} for the API, which checks it
   (llm_chat/services/need_help.py). Needs escapeHtml from shared.js. */
var NeedHelpEditor = (function () {
  var BUTTONS = 3;
  var KINDS = [
    ['', 'No button'],
    ['send', 'Sends a message'],
    ['guide', 'Opens the chat’s guide'],
    ['link', 'Goes to a link'],
  ];
  var VALUE_HINT = {
    send: 'The message it sends, for example: Star, can you help me with this?',
    link: 'https://… or mailto:…',
  };

  function label(text, control) {
    return '<label class="block"><span class="mb-1 block text-xs font-medium uppercase tracking-wide text-stone-500">' +
      text + '</span>' + control + '</label>';
  }

  function buttonRow(b, i, inputClass) {
    var kind = b.kind || '';
    var options = KINDS.map(function (k) {
      return '<option value="' + k[0] + '"' + (k[0] === kind ? ' selected' : '') + '>' + k[1] + '</option>';
    }).join('');
    var needsValue = kind === 'send' || kind === 'link';
    return '<div data-nh-button class="grid grid-cols-1 gap-2 sm:grid-cols-[11rem_1fr]">' +
      '<select data-nh-kind aria-label="Button ' + (i + 1) + ': what it does" class="' + inputClass + ' cursor-pointer">' + options + '</select>' +
      '<input type="text" data-nh-label maxlength="40" value="' + escapeHtml(b.label || '') + '"' +
        ' aria-label="Button ' + (i + 1) + ': label" placeholder="Label, for example: Ask Star"' +
        ' class="' + inputClass + (kind ? '' : ' hidden') + '">' +
      '<input type="text" data-nh-value maxlength="500" value="' + escapeHtml(b.value || '') + '"' +
        ' aria-label="Button ' + (i + 1) + ': message or link" placeholder="' + escapeHtml(VALUE_HINT[kind] || '') + '"' +
        ' class="' + inputClass + ' sm:col-start-2' + (needsValue ? '' : ' hidden') + '">' +
      '</div>';
  }

  function html(content, inputClass) {
    content = content || {};
    var buttons = (content.buttons || []).slice(0, BUTTONS);
    while (buttons.length < BUTTONS) buttons.push({});
    return '<div data-nh-root class="space-y-3">' +
      label('Heading', '<input type="text" data-nh-heading maxlength="80" value="' + escapeHtml(content.heading || '') + '" placeholder="Stuck on this exercise?" class="' + inputClass + '">') +
      label('Message', '<textarea data-nh-message maxlength="1000" rows="3" placeholder="What to try when you’re stuck. A blank line starts a new paragraph." class="' + inputClass + '">' + escapeHtml(content.message || '') + '</textarea>') +
      '<fieldset class="space-y-2"><legend class="mb-1 text-xs font-medium uppercase tracking-wide text-stone-500">Buttons</legend>' +
        buttons.map(function (b, i) { return buttonRow(b, i, inputClass); }).join('') +
        '<p class="text-xs text-stone-400">A guide button shows only in chats that have a guide. Links must start with https:// or mailto:. Every Need help? also links to Get help now, for a crisis.</p>' +
      '</fieldset>' +
      '</div>';
  }

  // Show the label and value fields a button's kind needs.
  document.addEventListener('change', function (event) {
    var select = event.target.closest('[data-nh-kind]');
    if (!select) return;
    var row = select.closest('[data-nh-button]');
    var kind = select.value;
    var value = row.querySelector('[data-nh-value]');
    row.querySelector('[data-nh-label]').classList.toggle('hidden', !kind);
    value.classList.toggle('hidden', kind !== 'send' && kind !== 'link');
    value.placeholder = VALUE_HINT[kind] || '';
  });

  function read(root) {
    root = root.querySelector('[data-nh-root]') || root;
    var buttons = [];
    root.querySelectorAll('[data-nh-button]').forEach(function (row) {
      var kind = row.querySelector('[data-nh-kind]').value;
      if (!kind) return;
      buttons.push({
        kind: kind,
        label: row.querySelector('[data-nh-label]').value,
        value: kind === 'guide' ? '' : row.querySelector('[data-nh-value]').value,
      });
    });
    return {
      heading: root.querySelector('[data-nh-heading]').value,
      message: root.querySelector('[data-nh-message]').value,
      buttons: buttons,
    };
  }

  return { html: html, read: read };
})();
