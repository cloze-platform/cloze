"""Inline SVG icons for the participant pages.

Templates call icon("home") and status_icon("started"). Every icon is
decorative (aria-hidden): the text beside it, or the control's aria-label,
carries the meaning. An unknown name raises, so a typo fails a test instead of
rendering an empty box.
"""

from markupsafe import Markup, escape

# 24×24 stroke paths, drawn with currentColor.
ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-6h4v6"/>',
    "notebook": '<path d="M7 3h10a1 1 0 0 1 1 1v17l-6-4-6 4V4a1 1 0 0 1 1-1z"/>',
    "shield": '<path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z"/>',
    "page": '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    "report": '<path d="M5 20V11M12 20V5M19 20v-6"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "heart": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    "alert": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 6-6 6 6 6"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "send": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "sign-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.9.6c0 1.7-2.5 2.1-2.5 3.8"/><path d="M12 17h.01"/>',
}

# 16×16 filled status marks for exercises.
STATUS_ICONS = {
    "finished": '<circle cx="8" cy="8" r="8" fill="var(--p-done-fill)"/>'
                '<path d="M4.8 8.2l2.1 2.1 4.3-4.5" fill="none" stroke="#FFFFFF" stroke-width="1.6" '
                'stroke-linecap="round" stroke-linejoin="round"/>',
    "started": '<circle cx="8" cy="8" r="6.75" fill="none" stroke="var(--p-accent)" stroke-width="1.5"/>'
               '<path d="M8 3.5a4.5 4.5 0 0 1 0 9z" fill="var(--p-accent)"/>',
    "not_started": '<circle cx="8" cy="8" r="6.75" fill="none" stroke="var(--p-ring)" stroke-width="1.5"/>',
}


def icon(name, size=18, cls="", stroke_width=1.8):
    paths = ICONS[name]
    cls_attr = f' class="{escape(cls)}"' if cls else ""
    return Markup(
        f'<svg aria-hidden="true" focusable="false"{cls_attr} width="{int(size)}" height="{int(size)}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{float(stroke_width):g}" '
        f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )


def status_icon(state, size=16, cls=""):
    paths = STATUS_ICONS[state]
    cls_attr = f' class="{escape(cls)}"' if cls else ""
    return Markup(
        f'<svg aria-hidden="true" focusable="false"{cls_attr} width="{int(size)}" height="{int(size)}" '
        f'viewBox="0 0 16 16">{paths}</svg>'
    )
