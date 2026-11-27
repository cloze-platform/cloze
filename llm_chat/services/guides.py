"""Guides: checking what researchers write, finding a chat's guide, and (only
when the team turns it on) giving the model the guide's text.

A guide is the first researcher-written Markdown that participants see with
images, so it is checked twice: here, on save, every image must be a
/media/<public_id> from the researcher's own library; and in the browser,
renderGuideMarkdown (static/js/shared.js) keeps only safe tags and drops any
other image. Replies keep their own, stricter, rendering.
"""
import re

from ..extensions import db
from ..media import access
from ..models import Guide, MediaAsset
from ..utils.settings_resolution import get_provider_id_for_patient

# Markdown images ![alt](src "title") and <img ... src=...> written as HTML.
_MD_IMAGE = re.compile(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)')
_HTML_IMAGE = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*["\']?([^"\'\s>]+)', re.IGNORECASE)
_MEDIA_SRC = re.compile(r'^/media/([0-9a-fA-F-]{36})(?:\?r=(?:display|thumb))?$')

# Heading for the guide's text when the model is given it. It comes after the
# chat's composed prompt, so the universal safety layers stay first.
MODEL_HEADING = "## The exercise guide\n\nThe participant can read this guide beside the chat."


def image_sources(body):
    return _MD_IMAGE.findall(body or '') + _HTML_IMAGE.findall(body or '')


def _media_id(src):
    match = _MEDIA_SRC.match(src)
    return access.canonical_id(match.group(1)) if match else None


def apply_guide_fields(guide, data, researcher):
    """Copy title and body_md onto a Guide. Every image must be in the
    researcher's library; one already in the guide may stay after it has
    left the library (places already using an image keep it). Raises
    ValueError with a message safe to show."""
    if 'title' in data or guide.id is None:
        title = data.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Give the guide a title.')
        if len(title.strip()) > Guide.TITLE_LIMIT:
            raise ValueError(f'A title can be at most {Guide.TITLE_LIMIT} characters.')
        guide.title = title.strip()
    if 'body_md' in data:
        body = data.get('body_md') or ''
        if not isinstance(body, str):
            raise ValueError('The guide must be text.')
        if len(body) > Guide.BODY_LIMIT:
            raise ValueError(f'A guide can be at most {Guide.BODY_LIMIT:,} characters.')
        already = {_media_id(s) for s in image_sources(guide.body_md)} - {None}
        for src in image_sources(body):
            public_id = _media_id(src)
            if public_id is None:
                raise ValueError('Images in a guide must come from your media library.')
            if public_id in already:
                continue
            asset = access.owned_asset(researcher, public_id)
            if asset is None or asset.kind != MediaAsset.KIND_IMAGE:
                raise ValueError('Images in a guide must come from your media library.')
        guide.body_md = body


def apply_chat_guide_fields(chat, data, researcher):
    """Copy guide_id, guide_opens_on_start and guide_to_model onto a FlowChat.
    The guide must be one of the researcher's own."""
    if 'guide_id' in data:
        guide_id = data['guide_id']
        if guide_id in (None, ''):
            chat.guide_id = None
        elif guide_id == chat.guide_id:
            pass   # unchanged
        else:
            guide = db.session.get(Guide, guide_id) if isinstance(guide_id, int) and not isinstance(guide_id, bool) else None
            if guide is None or guide.owner_id != researcher.id or guide.deleted_at is not None:
                raise ValueError('That guide isn\'t one of yours.')
            chat.guide_id = guide.id
    for key in ('guide_opens_on_start', 'guide_to_model'):
        if key in data:
            if not isinstance(data[key], bool):
                raise ValueError(f'{key} must be true or false.')
            setattr(chat, key, data[key])


def guide_for_template(template, participant):
    """(Guide, opens_on_start, to_model) for a participant's chat, or
    (None, False, False). Read live, under the same rule as greetings, casts
    and media: only a chat from the participant's own researcher counts."""
    chat = template.flow_chat if template is not None else None
    if chat is None or not chat.guide_id:
        return None, False, False
    provider_id = get_provider_id_for_patient(participant.id)
    if chat.phase.flow.provider_id != provider_id:
        return None, False, False
    guide = db.session.get(Guide, chat.guide_id)
    if guide is None or guide.owner_id != provider_id or guide.deleted_at is not None:
        return None, False, False
    return guide, bool(chat.guide_opens_on_start), bool(chat.guide_to_model)


def with_guide(system_prompt, template, participant):
    """The system prompt to send, with the guide's text after it when the
    team chose to give it to the model. The stored prompt never changes, so
    editing the guide reaches chats already under way."""
    guide, _, to_model = guide_for_template(template, participant)
    if guide is None or not to_model or not guide.body_md.strip():
        return system_prompt
    section = f"{MODEL_HEADING}\n\n# {guide.title}\n\n{guide.body_md.strip()}"
    return f"{system_prompt}\n\n{section}" if system_prompt else section
