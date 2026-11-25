"""When and why a conversation ended (Conversation.ended_at, end_reason).

A conversation is Finished once ended_at is set, and stays finished: sending
to it is refused with its reason, even if the setting behind the reason
changes later (a raised turn limit doesn't reopen a chat).

How each reason is recorded:
  turn_limit     by the send that uses the last turn (routes/conversations.py)
  window_closed  the first time anyone reads the conversation after its chat
                 window ends (stamp_window_closed), and by migrate_schema.py
                 for windows that ended before the columns existed

Recording an end never touches updated_at, which orders the participant's
chats by their last activity.
"""

import time

from sqlalchemy import or_, update
from sqlalchemy.orm.attributes import set_committed_value

from ..extensions import db
from ..models import ChatWindow, Conversation

CLOSED_STATUSES = ("generating_report", "report_ready")


def end(conversation, reason, at=None):
    """Record that the conversation ended, unless it already has. Returns
    True if this call ended it. Doesn't commit."""
    if conversation.ended_at is not None:
        return False
    at = time.time() if at is None else at
    db.session.flush()
    # A bulk UPDATE, so updated_at keeps its value: set through the ORM, the
    # column's onupdate would move it to now.
    result = db.session.execute(
        update(Conversation)
        .where(Conversation.id == conversation.id, Conversation.ended_at.is_(None))
        .values(ended_at=at, end_reason=reason, updated_at=Conversation.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:      # ended meanwhile by another request
        db.session.refresh(conversation, ["ended_at", "end_reason"])
        return False
    # The row is written. Record the values on the object as already saved,
    # so the next flush doesn't write them again.
    set_committed_value(conversation, "ended_at", at)
    set_committed_value(conversation, "end_reason", reason)
    return True


def window_has_ended(window, now=None):
    return window is not None and window.compute_status(now) in CLOSED_STATUSES


def stamp_window_closed(conversation, window, now=None):
    """End the conversation as window_closed if its window has ended. The
    time recorded is when the window closed, not when this noticed it.
    Returns True if it ended the conversation. Doesn't commit."""
    if conversation.ended_at is not None or not window_has_ended(window, now):
        return False
    now = time.time() if now is None else now
    return end(conversation, Conversation.WINDOW_CLOSED, at=min(window.end_date, now))


def backfill_window_closed(now=None):
    """One-off, for migrate_schema.py: end every conversation whose window has
    already ended. Returns how many it marked."""
    now = time.time() if now is None else now
    rows = (db.session.query(Conversation, ChatWindow)
            .join(ChatWindow, Conversation.window_id == ChatWindow.id)
            .filter(Conversation.ended_at.is_(None),
                    or_(ChatWindow.end_date < now, ChatWindow.status.in_(CLOSED_STATUSES)))
            .all())
    marked = sum(1 for conversation, window in rows if stamp_window_closed(conversation, window, now))
    db.session.commit()
    return marked
