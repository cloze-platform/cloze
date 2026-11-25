"""The greeting shown in an empty chat: an image above one line of text.

A researcher sets a default (ProviderFeatureFlags), and each study-design chat
can override the text, the image or both (FlowChat). The greeting is resolved
when a participant opens a chat, so edits reach participants already enrolled.
"""
from ..extensions import db
from ..media import access
from ..models import ChatTemplate, MediaAsset, ProviderFeatureFlags
from ..utils.settings_resolution import get_provider_id_for_patient

GREETING_TEXT_MAX = 200
DEFAULT_GREETING_TEXT = 'Send a message to get started.'


def apply_greeting_fields(target, data, researcher):
    """Copy greeting_text / greeting_asset_id from request data onto a FlowChat
    or ProviderFeatureFlags. A newly chosen image must be in the researcher's
    own library. Raises ValueError with a message safe to show."""
    if 'greeting_text' in data:
        text = data['greeting_text']
        if text is not None and not isinstance(text, str):
            raise ValueError('Greeting text must be text.')
        text = (text or '').strip()
        if len(text) > GREETING_TEXT_MAX:
            raise ValueError(f'Greeting text must be {GREETING_TEXT_MAX} characters or fewer.')
        target.greeting_text = text or None

    if 'greeting_asset_id' in data:
        public_id = data['greeting_asset_id']
        current = target.greeting_asset
        if not public_id:
            target.greeting_asset_id = None
        elif current is not None and current.public_id == access.canonical_id(public_id):
            # Unchanged. It may have been removed from the library since: places
            # already using an image keep it, so saving other edits mustn't fail.
            pass
        else:
            asset = access.owned_asset(researcher, public_id)
            if asset is None or asset.kind != MediaAsset.KIND_IMAGE:
                raise ValueError('That image is not in your media library.')
            target.greeting_asset_id = asset.id


def resolve_greeting(conversation):
    """{'text', 'image_url', 'alt'} for a conversation. Each part comes from the
    chat's override, else the researcher's default; the text finally falls back
    to a built-in line, and the image to none (the page shows a default icon)."""
    template = db.session.get(ChatTemplate, conversation.template_id) if conversation.template_id else None
    chat = template.flow_chat if template else None

    # The participant's current researcher decides, the same rule as for
    # loading media (access.can_view), not whoever created the chat. A chat
    # from another researcher's study (a reassigned participant) is ignored.
    provider_id = get_provider_id_for_patient(conversation.user_id)
    flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first() if provider_id else None
    if chat is not None and chat.phase.flow.provider_id != provider_id:
        chat = None

    text = (chat and chat.greeting_text) or (flags and flags.greeting_text) or DEFAULT_GREETING_TEXT
    # Only offer an image the participant will actually be allowed to load.
    candidates = [chat and chat.greeting_asset, flags and flags.greeting_asset]
    asset = next((a for a in candidates if a and access.can_view(conversation.user, a)), None)
    return {
        'text': text,
        'image_url': asset.url if asset else None,
        'alt': (asset.alt_text or '') if asset else '',
    }

