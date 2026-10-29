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
