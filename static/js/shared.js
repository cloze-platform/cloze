/* shared.js — Cloze common utilities
   Loaded by base.html on all authenticated pages. */

// ── Text helpers ──────────────────────────────────────────────

function escapeHtml(s) {
  if (!s) return '';
  return s.replace(/[&<>"'`=\/]/g, function (ch) {
    return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;',
             "'":'&#39;', '`':'&#96;', '=':'&#61;', '/':'&#47;' }[ch] || ch;
  });
}

// Model replies are untrusted: a participant can steer a model into emitting
// HTML, and providers view the same replies. Render Markdown, then keep only
// the tags Markdown itself produces. No images (a URL can carry conversation
// text off-site) and no class or style attributes (Tailwind would let a reply
// restyle the page). Without marked and DOMPurify (both loaded by
// _markdown_scripts.html), fall back to escaped plain text, never raw HTML.
var MARKDOWN_ALLOWED_TAGS = ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'em', 'del', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li', 'a',
  'table', 'thead', 'tbody', 'tr', 'th', 'td'];
var MARKDOWN_ALLOWED_ATTR = ['href', 'title', 'align', 'start'];

function renderMarkdown(text) {
  var plain = escapeHtml(text || '').replace(/\n/g, '<br>');
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return plain;
  try {
    return DOMPurify.sanitize(marked.parse(text || ''), {
      ALLOWED_TAGS: MARKDOWN_ALLOWED_TAGS,
      ALLOWED_ATTR: MARKDOWN_ALLOWED_ATTR,
    });
  } catch (e) {
    console.error('Markdown rendering failed:', e);
    return plain;
  }
}

function highlight(text, query) {
  if (!text || !query) return escapeHtml(text || '');
  var i = text.toLowerCase().indexOf(query.toLowerCase());
  if (i === -1) return escapeHtml(text);
  var before = escapeHtml(text.slice(0, i));
  var match  = escapeHtml(text.slice(i, i + query.length));
  var after  = escapeHtml(text.slice(i + query.length));
  return before + '<mark class="rounded bg-amber-100 px-0.5">' + match + '</mark>' + after;
}

function snippet(text, query, radius) {
  radius = radius || 40;
  var t = text || '';
  var q = (query || '').toLowerCase();
  var i = t.toLowerCase().indexOf(q);
  if (i === -1) return escapeHtml(t.slice(0, radius * 2));
  var start = Math.max(0, i - radius);
  var end   = Math.min(t.length, i + q.length + radius);
  var pre = start > 0 ? '\u2026' : '';
  var suf = end < t.length ? '\u2026' : '';
  return pre + highlight(t.slice(start, end), query) + suf;
}

// ── Date / time formatting ────────────────────────────────────

function formatDate(timestamp) {
  if (!timestamp) return '\u2014';
  var d = new Date(timestamp * 1000);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDateTime(timestamp) {
  if (!timestamp) return '\u2014';
  var d = new Date(timestamp * 1000);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return '\u2014';
  var now = Date.now() / 1000;
  var diff = now - timestamp;
  if (diff < 3600) {
    var mins = Math.max(1, Math.floor(diff / 60));
    return mins + ' min' + (mins !== 1 ? 's' : '') + ' ago';
  } else if (diff < 86400) {
    var hours = Math.floor(diff / 3600);
    return hours + ' hour' + (hours !== 1 ? 's' : '') + ' ago';
  } else {
    var days = Math.floor(diff / 86400);
    return days + ' day' + (days !== 1 ? 's' : '') + ' ago';
  }
}

// ── Status constants ──────────────────────────────────────────

var STATUS_LABELS = {
  scheduled:         'Scheduled',
  active:            'Active',
  generating_report: 'Generating Report',
  report_ready:      'Report Ready'
};

var STATUS_CLASSES = {
  scheduled:         'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200',
  active:            'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200',
  generating_report: 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200',
  report_ready:      'bg-violet-50 text-violet-700 ring-1 ring-inset ring-violet-200'
};

// ── Dialogs (replaces browser prompt/confirm/alert) ──────────

/**
 * Show a custom dialog. Returns a Promise.
 *
 * Usage:
 *   var name = await showDialog({ title: 'Rename', input: 'current name', confirmText: 'Save' });
 *   if (name === null) return; // cancelled
 *
 *   var ok = await showDialog({ title: 'Delete?', message: 'This cannot be undone.', confirmText: 'Delete', danger: true });
 *   if (!ok) return; // cancelled
 */
function showDialog(options) {
  return new Promise(function(resolve) {
    var overlay = document.getElementById('dialogOverlay');
    var title = document.getElementById('dialogTitle');
    var message = document.getElementById('dialogMessage');
    var input = document.getElementById('dialogInput');
    var cancelBtn = document.getElementById('dialogCancel');
    var confirmBtn = document.getElementById('dialogConfirm');

    title.textContent = options.title || '';
    message.textContent = options.message || '';
    message.classList.toggle('hidden', !options.message);
    confirmBtn.textContent = options.confirmText || 'Confirm';

    if (options.danger) {
      confirmBtn.className = 'rounded-lg px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 transition-colors';
    } else {
      confirmBtn.className = 'rounded-lg px-4 py-2 text-sm font-medium text-white bg-cloze-indigo hover:bg-cloze-hover transition-colors';
    }

    if (options.input !== undefined) {
      input.classList.remove('hidden');
      input.value = options.input || '';
      input.placeholder = options.placeholder || '';
      setTimeout(function() { input.focus(); input.select(); }, 50);
    } else {
      input.classList.add('hidden');
    }

    overlay.classList.remove('hidden');
    overlay.classList.add('flex');

    function cleanup() {
      overlay.classList.add('hidden');
      overlay.classList.remove('flex');
      cancelBtn.onclick = null;
      confirmBtn.onclick = null;
      input.onkeydown = null;
    }

    cancelBtn.onclick = function() { cleanup(); resolve(null); };
    confirmBtn.onclick = function() {
      cleanup();
      resolve(options.input !== undefined ? input.value : true);
    };
    if (options.input !== undefined) {
      input.onkeydown = function(e) {
        if (e.key === 'Enter') confirmBtn.click();
        if (e.key === 'Escape') cancelBtn.click();
      };
    }
  });
}

// ── Auto-resizing textareas ──────────────────────────────────

function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = textarea.scrollHeight + 'px';
}

function initAutoResize(selector) {
  document.querySelectorAll(selector || 'textarea.auto-resize').forEach(function(ta) {
    ta.style.overflow = 'hidden';
    ta.style.resize = 'none';
    ta.addEventListener('input', function() { autoResize(this); });
    // Initial sizing
    setTimeout(function() { autoResize(ta); }, 0);
  });
}

// ── Auth ──────────────────────────────────────────────────────

async function logout() {
  await fetch('/logout');
  window.location.href = '/login';
}

// ── Sidebar toggle (mobile) ──────────────────────────────────

(function initSidebar() {
  var menuBtn = document.getElementById('menuBtn');
  var sidebar = document.getElementById('sidebar');
  var overlay = document.getElementById('overlay');

  if (!menuBtn || !sidebar) return;

  function openSide() {
    sidebar.classList.remove('-translate-x-full');
    if (overlay) overlay.classList.remove('hidden');
  }
  function closeSide() {
    sidebar.classList.add('-translate-x-full');
    if (overlay) overlay.classList.add('hidden');
  }

  menuBtn.addEventListener('click', function () {
    sidebar.classList.contains('-translate-x-full') ? openSide() : closeSide();
  });
  if (overlay) overlay.addEventListener('click', closeSide);
  if (window.innerWidth >= 1024) sidebar.classList.remove('-translate-x-full');
})();

// ── Active nav link highlighting ─────────────────────────────

(function markActive() {
  var path = location.pathname.replace(/\/+$/, '');
  var hash = location.hash || '';
  var fullUrl = path + hash;
  document.querySelectorAll('#sidebar a[href]').forEach(function (a) {
    var href = a.getAttribute('href').replace(/\/+$/, '');
    // For hash-based links (e.g. /admin/dashboard#patients), match exactly
    var isMatch = false;
    if (href.indexOf('#') !== -1) {
      isMatch = (href === fullUrl);
    } else {
      isMatch = href && (href === path || (href !== '/' && path.startsWith(href)));
    }
    if (isMatch) {
      a.classList.remove('text-stone-600', 'hover:bg-violet-50');
      a.classList.add('bg-cloze-lavender', 'text-cloze-indigo', 'font-medium');
      var icon = a.querySelector('svg');
      if (icon) {
        icon.classList.remove('text-stone-400');
        icon.classList.add('text-cloze-indigo');
      }
    }
  });
})();
