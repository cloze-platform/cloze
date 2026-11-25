"""Instance colour theme.

CLOZE_THEME is an optional JSON object of colour overrides, e.g.
{"primary": "#1C488F", "hover": "#223D71"}. Anything not given keeps the Cloze
default. Templates get the result as CSS variables (templates/_theme_vars.html),
which the Tailwind colours and the dark-mode styles read.
"""

import json
import re

DEFAULTS = {
    "primary": "#5B5FC7",        # buttons, links, active states
    "hover": "#4E51B0",          # primary, darker
    "accent": "#7DBBDA",         # secondary accent
    "tint": "#EEEAF6",           # light highlight backgrounds
    "on_dark": "#C4B5FD",        # links and active text in dark mode
    "on_dark_hover": "#DDD6FE",
    "dark_page": "#1C1926",      # dark-mode surfaces, darkest to lightest
    "dark_sidebar": "#15121E",
    "dark_card": "#221F2E",
    "dark_raised": "#2A2535",
    "dark_border": "#3A3545",
}

# Tailwind's violet, which the templates use as a soft brand tint (bg-violet-50
# and so on). A theme with its own primary gets a matching ramp instead.
SOFT_DEFAULTS = {
    50: "#F5F3FF", 100: "#EDE9FE", 200: "#DDD6FE", 300: "#C4B5FD",
    400: "#A78BFA", 500: "#8B5CF6", 600: "#7C3AED", 700: "#6D28D9",
}

# Colours the chat views and main action buttons use. Not set directly: a
# custom theme derives them (see _derived), the Cloze theme keeps these.
DERIVED_DEFAULTS = {
    "chat-page": "#F8F6FC", "chat-page-dark": "#1E1B28",
    "bubble": "#E9E5F5", "bubble-text": "#2D2A3E",
    "bubble-dark": "#3D3A6E", "bubble-text-dark": "#E8E5F0",
    "action": "#312E81", "action-hover": "#3D3A94",
}

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_theme(raw):
    """Merge a CLOZE_THEME JSON string over the defaults. Raises ValueError."""
    overrides = {}
    if raw:
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"CLOZE_THEME is not valid JSON ({e.msg})") from None
        if not isinstance(overrides, dict):
            raise ValueError("CLOZE_THEME must be a JSON object")
        unknown = sorted(set(overrides) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"CLOZE_THEME has unknown keys: {', '.join(unknown)} "
                             f"(allowed: {', '.join(DEFAULTS)})")
        bad = sorted(k for k, v in overrides.items() if not (isinstance(v, str) and _HEX.match(v)))
        if bad:
            raise ValueError(f"CLOZE_THEME values must be #RRGGBB colours: {', '.join(bad)}")

    theme = {**DEFAULTS, **{k: v.upper() for k, v in overrides.items()}}
    theme["soft"] = _soft_ramp(theme) if "primary" in overrides else dict(SOFT_DEFAULTS)
    theme["derived"] = _derived(theme) if overrides else dict(DERIVED_DEFAULTS)
    return theme


def css_variables(theme):
    """CSS custom property declarations for :root. Each colour also gets an
    "-rgb" form ("R G B"), which Tailwind needs for opacity modifiers."""
    colours = {("brand-" if not key.startswith("dark_") else "") + key.replace("_", "-"): theme[key]
               for key in DEFAULTS}
    colours.update({f"soft-{shade}": value for shade, value in theme["soft"].items()})
    colours.update(theme["derived"])
    return " ".join(f"--{name}: {value}; --{name}-rgb: {' '.join(map(str, _rgb(value)))};"
                    for name, value in colours.items())


def _rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _mix(colour, share, base="#FFFFFF"):
    """colour blended into base (white by default); share is the fraction of colour kept."""
    return "#%02X%02X%02X" % tuple(round(c * share + b * (1 - share)) for c, b in zip(_rgb(colour), _rgb(base)))


def _derived(theme):
    p = theme["primary"]
    return {
        "chat-page": _mix(p, 0.035), "chat-page-dark": theme["dark_page"],
        "bubble": _mix(p, 0.14), "bubble-text": theme["hover"],
        "bubble-dark": _mix(p, 0.45, theme["dark_raised"]), "bubble-text-dark": _mix(p, 0.08),
        "action": theme["hover"], "action-hover": p,
    }


def _soft_ramp(theme):
    p = theme["primary"]
    return {50: _mix(p, 0.06), 100: _mix(p, 0.12), 200: _mix(p, 0.24), 300: _mix(p, 0.42),
            400: _mix(p, 0.65), 500: _mix(p, 0.85), 600: p, 700: theme["hover"]}


# ── Participant pages (templates/participant/) ─────────────────────────────
# The redesigned participant pages use their own small set of colour tokens.
# Neutrals and status colours are fixed; everything tinted is mixed from the
# instance's primary, and dark mode is built on the instance's dark_* colours,
# so a CLOZE_THEME restyles these pages too.

def luminance(colour):
    """WCAG relative luminance of a #RRGGBB colour."""
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two #RRGGBB colours (1 to 21)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


_INK, _WHITE = "#18181F", "#FFFFFF"


def participant_tokens(theme):
    """(light, dark) dicts of participant colour tokens, without the --p- prefix."""
    p, hover = theme["primary"], theme["hover"]
    on_accent = _WHITE if contrast(_WHITE, p) >= 4.5 else _INK
    shared = {
        "accent": p, "accent-hover": hover, "on-accent": on_accent,
        "night": _mix(p, 0.22, "#100E20"),  # the closed-hours page, the same in both modes
    }
    light = {
        **shared,
        "page": _WHITE, "menu": "#F7F7FA", "surface": _WHITE, "quiet": "#F7F7FA",
        "raised": "#F1F1F6", "chat": _WHITE,
        "line": "#E7E7EE", "line-strong": "#DADAE3",
        "ink": _INK, "ink-2": "#2C2C36", "ink-3": "#4B4B58", "hint": "#6B6B78", "ring": "#8E8E9C",
        "accent-soft": _mix(p, 0.10), "accent-line": _mix(p, 0.40), "accent-ink": _mix(p, 0.78, "#000000"),
        "focus": p,
        "done": "#13795B", "done-fill": "#13795B", "done-soft": "#E6F4EE",
        "waiting": "#8A5300", "waiting-soft": "#FFF3DC", "waiting-line": "#F1D9A6",
        "help": "#A3213D", "help-soft": "#FDECEF", "help-line": "#F6C9D2",
    }
    page, card, raised, border = (theme[k] for k in ("dark_page", "dark_card", "dark_raised", "dark_border"))
    accent_ink_dark = _mix(p, 0.42)
    dark = {
        **shared,
        "page": page, "menu": theme["dark_sidebar"], "surface": card, "quiet": card,
        "raised": raised, "chat": theme["derived"]["chat-page-dark"],
        "line": border, "line-strong": _mix(_WHITE, 0.10, border),
        "ink": "#F1EFF6", "ink-2": "#DCD9E4", "ink-3": "#C2BFCC", "hint": "#A3A0AE", "ring": "#7C788A",
        "accent-soft": _mix(p, 0.22, page), "accent-line": _mix(p, 0.50, page), "accent-ink": accent_ink_dark,
        "focus": accent_ink_dark,
        "done": "#5FD3A6", "done-fill": "#2FA67A", "done-soft": "#16302A",
        "waiting": "#F2C46B", "waiting-soft": "#3A2E16", "waiting-line": "#5A4520",
        "help": "#FF9DB0", "help-soft": "#3B1B25", "help-line": "#5C2A38",
    }
    return light, dark


def participant_css(theme):
    """CSS for the participant tokens: light on :root, dark under prefers-color-scheme."""
    light, dark = participant_tokens(theme)

    def declarations(tokens):
        return " ".join(f"--p-{name}: {value};" for name, value in tokens.items())

    return (f":root {{ {declarations(light)} }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root {{ {declarations(dark)} }} }}")
