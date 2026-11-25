"""Links from participants' chats to the study-design chat they came from.

Enrollment copies each study-design chat (FlowChat) into the participant's
window as a ChatTemplate, which records the source in flow_chat_id. Settings
that should reach participants already enrolled are read through that link
rather than copied. Deleting a study-design chat clears it
(routes/provider.py, _unlink_templates).
"""
from ..extensions import db
from ..models import ChatTemplate, ChatWindow, FlowChat


def link_templates_to_flow_chats():
    """One-off backfill for chats generated before ChatTemplate.flow_chat_id
    existed: link each to the study-design chat it came from, when exactly one
    chat in the window's phase has the same title. Returns how many were linked."""
    linked = 0
    templates = (ChatTemplate.query.join(ChatWindow, ChatTemplate.window_id == ChatWindow.id)
                 .filter(ChatTemplate.flow_chat_id.is_(None), ChatWindow.phase_id.isnot(None))
                 .all())
    for template in templates:
        matches = FlowChat.query.filter_by(phase_id=template.window.phase_id, title=template.title).all()
        if len(matches) == 1:
            template.flow_chat_id = matches[0].id
            linked += 1
    db.session.commit()
    return linked
