"""Need help?: what the study team says to a participant who's stuck on an
exercise. It sits in the reply box and is kept apart from Get help now,
which is for a crisis and the same everywhere.

The content is a heading, a message and up to three buttons, each one of:
- send: puts a message in the reply box and sends it ("Star, help");
- guide: opens the chat's guide (left out when the chat has no guide);
- link: opens a link (https:// or mailto:), for example to contact the team.

Each researcher writes a default (ProviderFeatureFlags.need_help). Each
study-design chat uses it, writes its own (need_help_mode 'custom'), or has
none ('off'). Read when the chat is shown, so edits reach chats under way.
"""
import json
import re

from ..models import ProviderFeatureFlags
from ..utils.settings_resolution import get_provider_id_for_patient

HEADING_LIMIT = 80
MESSAGE_LIMIT = 1000
BUTTON_LIMIT = 3
LABEL_LIMIT = 40
SEND_LIMIT = 500
LINK_LIMIT = 500
KINDS = ("send", "guide", "link")
MODES = ("default", "custom", "off")
DEFAULT_HEADING = "Stuck on this exercise?"
_LINK = re.compile(r"^(https://|mailto:)\S+$", re.IGNORECASE)


def _text(value, limit, what):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{what} can be at most {limit:,} characters.")
    return value


def clean(raw):
    """Checked Need help? content, or None when there's nothing in it.
    Raises ValueError with a message safe to show."""
    if raw in (None, ""):
        return None
    if not isinstance(raw, dict):
        raise ValueError("Need help? must have a heading, a message and buttons.")
    heading = _text(raw.get("heading"), HEADING_LIMIT, "The heading")
    message = _text(raw.get("message"), MESSAGE_LIMIT, "The message")
    buttons = raw.get("buttons") or []
    if not isinstance(buttons, list) or len(buttons) > BUTTON_LIMIT:
        raise ValueError(f"Need help? can have up to {BUTTON_LIMIT} buttons.")
    cleaned = []
    for button in buttons:
        if not isinstance(button, dict):
            raise ValueError("Each button needs a label and what it does.")
        kind = button.get("kind")
        if kind not in KINDS:
            raise ValueError("A button can send a message, open the guide, or go to a link.")
        label = _text(button.get("label"), LABEL_LIMIT, "A button's label")
        if not label:
            raise ValueError("Each button needs a label.")
        value = ""
        if kind == "send":
            value = _text(button.get("value"), SEND_LIMIT, "The message a button sends")
            if not value:
                raise ValueError(f"Write the message “{label}” sends.")
        elif kind == "link":
            value = _text(button.get("value"), LINK_LIMIT, "A link")
            if not _LINK.match(value):
                raise ValueError(f"“{label}” needs a link that starts with https:// or mailto:.")
        cleaned.append({"label": label, "kind": kind, "value": value})
    if not heading and not message and not cleaned:
        return None
    if not message and not cleaned:
        raise ValueError("Add a message or at least one button.")
    return {"heading": heading, "message": message, "buttons": cleaned}


def load(raw):
    """Stored content (JSON text) as a dict, or None."""
    try:
        value = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def apply_default(flags, data):
    """The researcher's default, from PUT /api/provider/my-flags."""
    if "need_help" in data:
        content = clean(data["need_help"])
        flags.need_help = json.dumps(content) if content else None


def apply_chat_fields(chat, data):
    """A study-design chat's mode and own content."""
    if "need_help_mode" in data:
        mode = data["need_help_mode"] or "default"
        if mode not in MODES:
            raise ValueError("Need help? is your default from Settings, written for this chat, or off.")
        chat.need_help_mode = None if mode == "default" else mode
    if "need_help" in data:
        content = clean(data["need_help"])
        chat.need_help = json.dumps(content) if content else None
    if chat.need_help_mode == "custom" and not chat.need_help:
        raise ValueError("Write this chat's Need help?, or use your default from Settings.")


def for_chat(template, participant, has_guide):
    """What a participant's chat shows under Need help?, or None for no button.
    Only a chat from the participant's own researcher counts, as with
    greetings, casts and guides."""
    provider_id = get_provider_id_for_patient(participant.id)
    chat = template.flow_chat if template is not None else None
    if chat is not None and chat.phase.flow.provider_id != provider_id:
        chat = None
    mode = (chat.need_help_mode if chat is not None else None) or "default"
    if mode == "off":
        return None
    if mode == "custom":
        content = load(chat.need_help)
    else:
        flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first() if provider_id else None
        content = load(flags.need_help) if flags else None
    if not content:
        return None
    buttons = [b for b in content.get("buttons", []) if b.get("kind") != "guide" or has_guide]
    message = content.get("message") or ""
    if not message and not buttons:
        return None
    return {
        "heading": content.get("heading") or DEFAULT_HEADING,
        "paragraphs": [p.strip() for p in re.split(r"\n\s*\n", message) if p.strip()],
        "buttons": buttons,
    }
