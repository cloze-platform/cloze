"""The safety information a participant agrees to before each conversation.

A study team can replace the built-in text (ProviderFeatureFlags.
safety_disclaimer_text) with blocks from the researcher settings page: a JSON
list of {type: text | warning | alert | checkbox, title?, content}. An admin
can also enter raw HTML there. Pages render blocks on the server; raw HTML is
only ever shown after DOMPurify cleans it in the browser.
"""

import json
import re

from markupsafe import Markup, escape

from ..models import ProviderFeatureFlags

DEFAULT_AGREEMENT = ("I understand this information and agree to use this conversation partner for "
                     "general discussion only, not for clinical treatment or emergencies.")


def safety_info(provider_id):
    """{"blocks": [...]} for team-written blocks, {"html": raw} for raw HTML,
    or None for the built-in text."""
    flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first() if provider_id else None
    raw = flags.safety_disclaimer_text if flags else None
    if not raw:
        return None
    try:
        blocks = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        blocks = None
    if isinstance(blocks, list):
        return {"blocks": [b for b in blocks if isinstance(b, dict)]}
    return {"html": raw}


def bold(text):
    """Escape text, then turn **this** into <strong>this</strong>."""
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text or ""))))
