"""Speakers: splitting a reply into the parts each character says.

The research team's prompt makes one model reply voice several characters, each
line starting with the character's name: "Star: ..." then "Sky: ...". In a
chat with a cast (FlowChat.speaker_ids), the participant's page shows each part
under that speaker's picture, name and role.

The split happens only when a reply is shown. The reply is stored, and sent
back to the model, exactly as the model wrote it: the prompt is the team's
research deliverable and has to work the same in Cloze as anywhere else.

The rule (stage 2 plan, decision 5):
- A line that starts with a cast member's name and a colon starts that
  speaker's part: "Sky:", "**Sky:**" and "**Sky**:" all count, in any case.
- Lines without a name continue the part they follow.
- Text before the first name belongs to the chat's main speaker (unnamed if
  there's none).
- Only the cast's names count. Anything else ("Narrator:", "You:", a name in
  the middle of a line) stays inside the current part.
"""
import json
import re
from dataclasses import dataclass

from ..extensions import db
from ..media import access
from ..models import MediaAsset, Speaker
from ..utils.settings_resolution import get_provider_id_for_patient

CAST_LIMIT = 10


@dataclass
class Part:
    speaker: object   # Speaker or None
    text: str


def _name_pattern(cast):
    names = sorted({s.name for s in cast if s.name}, key=len, reverse=True)
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in names)
    # "Sky:", "**Sky:**", "**Sky**:", with optional spaces; the name is then
    # followed by a colon, so "Skyler:" isn't "Sky".
    return re.compile(r"^[ \t]*(?:\*\*)?[ \t]*(?P<name>" + alternatives + r")[ \t]*(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]?",
                      re.IGNORECASE)


def split_reply(text, cast, main=None):
    """[Part] for a reply. With no cast, the whole reply as one unnamed part."""
    text = text or ""
    pattern = _name_pattern(cast or [])
    if pattern is None:
        return [Part(None, text)]
    by_name = {s.name.lower(): s for s in cast}

    parts, speaker, lines = [], main, []

    def flush():
        body = "\n".join(lines).strip("\n")
        if body.strip():
            if parts and parts[-1].speaker is speaker:
                parts[-1].text += "\n\n" + body
            else:
                parts.append(Part(speaker, body))

    for line in text.split("\n"):
        match = pattern.match(line)
        if match:
            flush()
            speaker, lines = by_name[match.group("name").lower()], []
            rest = line[match.end():]
            if rest.strip():
                lines.append(rest)
        else:
            lines.append(line)
    flush()
    return parts or [Part(main, text)]


# ── A chat's cast, read live ──────────────────────────────────

def cast_for_template(template, participant):
    """(cast, main) for a participant's chat template: the study-design chat's
    speakers in its order, and its main speaker. ([], None) when the chat has
    no cast, or it belongs to a researcher other than the participant's own
    (the same rule as greetings and media)."""
    chat = template.flow_chat if template is not None else None
    if chat is None or not chat.cast_ids:
        return [], None
    provider_id = get_provider_id_for_patient(participant.id)
    if chat.phase.flow.provider_id != provider_id:
        return [], None
    ids = chat.cast_ids
    found = {s.id: s for s in Speaker.query.filter(Speaker.id.in_(ids), Speaker.owner_id == provider_id,
                                                   Speaker.deleted_at.is_(None))}
    cast = [found[i] for i in ids if i in found]
    main = found.get(chat.main_speaker_id) if chat.main_speaker_id in ids else None
    return cast, main


def speaker_view(speaker, participant, initial=None):
    """What the participant's page shows for a speaker. Without a picture it
    shows `initial`: the first letter, or two when the cast shares one."""
    picture = speaker.picture
    return {
        "name": speaker.name,
        "role": speaker.role or "",
        "image_url": picture.url if picture is not None and access.can_view(participant, picture) else None,
        "initial": initial or speaker.name[:1].upper(),
    }


def _initials(cast):
    firsts = [s.name[:1].upper() for s in cast]
    return {s.id: (s.name[:2].title() if firsts.count(s.name[:1].upper()) > 1 else s.name[:1].upper())
            for s in cast}


def reply_parts(text, cast, main, participant):
    """[{speaker: view or None, text}] for a reply, or None when the chat has
    no cast (the page then shows the reply as it always has)."""
    if not cast:
        return None
    views = {}
    initials = _initials(cast)
    parts = []
    for part in split_reply(text, cast, main):
        view = None
        if part.speaker is not None:
            if part.speaker.id not in views:
                views[part.speaker.id] = speaker_view(part.speaker, participant, initials.get(part.speaker.id))
            view = views[part.speaker.id]
        parts.append({"speaker": view, "text": part.text})
    return parts


# ── Researcher input ──────────────────────────────────────────

def _text(data, key, limit, required=False, label=None):
    value = data.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label or key} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label or key} can be at most {limit} characters.")
    if required and not value:
        raise ValueError(f"Give the speaker a {label.lower() if label else key}.")
    return value or None


def apply_speaker_fields(speaker, data, researcher):
    """Copy name, role and picture onto a Speaker from request data. Names are
    unique per researcher, ignoring case, because replies are matched by name.
    The picture must be an image in the researcher's own library. Raises
    ValueError with a message safe to show."""
    if "name" in data or speaker.id is None:
        name = _text(data, "name", Speaker.NAME_LIMIT, required=True, label="Name")
        if ":" in name or "\n" in name:
            raise ValueError("A speaker's name can't contain a colon.")
        clash = (Speaker.query.filter(Speaker.owner_id == researcher.id, Speaker.deleted_at.is_(None),
                                      db.func.lower(Speaker.name) == name.lower()))
        if speaker.id is not None:
            clash = clash.filter(Speaker.id != speaker.id)
        if clash.first() is not None:
            raise ValueError(f"You already have a speaker called {name}.")
        speaker.name = name
    if "role" in data:
        speaker.role = _text(data, "role", Speaker.ROLE_LIMIT, label="Role")
    if "picture_id" in data:
        public_id = data["picture_id"]
        current = speaker.picture
        if not public_id:
            speaker.picture_asset_id = None
        elif current is not None and current.public_id == access.canonical_id(public_id):
            pass   # unchanged; it may have left the library since, which is fine
        else:
            asset = access.owned_asset(researcher, public_id)
            if asset is None or asset.kind != MediaAsset.KIND_IMAGE:
                raise ValueError("That picture is not in your media library.")
            speaker.picture_asset_id = asset.id


def apply_cast_fields(chat, data, researcher):
    """Copy speaker_ids (the cast, in order) and main_speaker_id onto a
    FlowChat. Every speaker must be one of the researcher's own; the main
    speaker must be in the cast. Raises ValueError with a message safe to show."""
    if "speaker_ids" in data:
        ids = data["speaker_ids"] or []
        if (not isinstance(ids, list) or len(ids) > CAST_LIMIT
                or any(not isinstance(i, int) or isinstance(i, bool) for i in ids) or len(set(ids)) != len(ids)):
            raise ValueError(f"A chat's cast is a list of up to {CAST_LIMIT} different speakers.")
        if ids:
            own = {s.id for s in Speaker.query.filter(Speaker.id.in_(ids), Speaker.owner_id == researcher.id,
                                                      Speaker.deleted_at.is_(None))}
            if set(ids) - own:
                raise ValueError("That speaker isn't one of yours.")
        chat.speaker_ids = json.dumps(ids) if ids else None
        if chat.main_speaker_id not in ids:
            chat.main_speaker_id = None
    if "main_speaker_id" in data:
        main = data["main_speaker_id"]
        if main in (None, ""):
            chat.main_speaker_id = None
        elif not isinstance(main, int) or isinstance(main, bool) or main not in chat.cast_ids:
            raise ValueError("The main speaker has to be in the chat's cast.")
        else:
            chat.main_speaker_id = main
