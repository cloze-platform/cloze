"""The participant's notebook, laid out as pages.

Entries are stored once (SavedSelection: a saved line, the participant's own
thought on it, who said it, and which messages it quotes). Pages are a way of
laying them out, not something stored: this module builds the "by exercise"
layout, with each exercise a page and each group of the study a chapter, in
the same order as the participant's Exercises menu. A layout by date can be
added later over the same entries (.docs/roadmap/notebook-design.md).
"""
import json
from dataclasses import dataclass, field

from ..extensions import db
from ..models import Conversation, Message, SavedSelection
from .speakers import cast_for_template, speaker_view

OTHER_CHAPTER = "Other chats"


@dataclass
class Entry:
    selection: SavedSelection
    page: "Page" = field(repr=False)
    speaker: dict | None = None     # speaker_view(), or None
    is_you: bool = False            # the participant's own words
    message_id: int | None = None   # the first message it quotes, for "See it in the chat"

    @property
    def id(self):
        return self.selection.id

    @property
    def text(self):
        return self.selection.selection_text

    @property
    def thought(self):
        return self.selection.note

    @property
    def created_at(self):
        return self.selection.created_at or 0

    @property
    def chat_url(self):
        url = f"/exercise/{self.page.conversation_id}"
        return f"{url}#m-{self.message_id}" if self.message_id else url


@dataclass
class Page:
    conversation_id: int
    title: str
    chapter: str
    exercise: object = None          # participant_nav.Exercise, or None for a chat outside the menu
    entries: list = field(default_factory=list)
    order: tuple = ()

    @property
    def url(self):
        return f"/notebook/page/{self.conversation_id}"

    @property
    def latest(self):
        return max((e.created_at for e in self.entries), default=0)

    @property
    def latest_entry(self):
        return max(self.entries, key=lambda e: (e.created_at, e.id)) if self.entries else None

    @property
    def thoughts(self):
        return sum(1 for e in self.entries if e.thought)


@dataclass
class Notebook:
    pages: list                      # in contents order
    chapters: list                   # [(chapter name, [Page])], in contents order

    @property
    def entries(self):
        return [e for p in self.pages for e in p.entries]

    def page_for(self, conversation_id):
        return next((p for p in self.pages if p.conversation_id == conversation_id), None)

    def neighbours(self, page):
        i = self.pages.index(page)
        return (self.pages[i - 1] if i > 0 else None,
                self.pages[i + 1] if i + 1 < len(self.pages) else None)


def _message_ids(selection):
    try:
        ids = json.loads(selection.message_ids or "[]")
    except (TypeError, ValueError):
        return []
    return [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]


def build(nav, user):
    """The participant's notebook, by exercise. Three queries plus one cast
    lookup per exercise that has a cast."""
    selections = (SavedSelection.query.filter_by(user_id=user.id)
                  .order_by(SavedSelection.created_at, SavedSelection.id).all())
    if not selections:
        return Notebook(pages=[], chapters=[])

    conv_ids = {s.conversation_id for s in selections}
    # Only lines from the participant's own conversations (saving checks this
    # too; the notebook doesn't rely on it).
    conversations = {c.id: c for c in Conversation.query.filter(Conversation.id.in_(conv_ids),
                                                                Conversation.user_id == user.id)}
    selections = [s for s in selections if s.conversation_id in conversations]
    if not selections:
        return Notebook(pages=[], chapters=[])
    wanted = {i for s in selections for i in _message_ids(s)}
    roles = ({m_id: (cid, role) for m_id, cid, role in db.session.query(Message.id, Message.conversation_id, Message.role)
              .filter(Message.id.in_(wanted))} if wanted else {})

    group_rank = {g.id: i for i, g in enumerate(nav.menu_groups)}
    pages, casts = {}, {}
    for s in selections:
        page = pages.get(s.conversation_id)
        if page is None:
            conv = conversations.get(s.conversation_id)
            ex = nav.exercise_for_conversation(s.conversation_id)
            if ex is not None:
                order = (0, group_rank.get(ex.group.id, len(group_rank)), ex.group.exercises.index(ex), 0)
                page = Page(s.conversation_id, ex.title, ex.group.name, ex, order=order)
                cast, _ = cast_for_template(ex.template, user)
                casts[s.conversation_id] = {sp.name.lower(): speaker_view(sp, user) for sp in cast}
            else:
                title = (conv.title if conv and conv.title else "A chat")
                page = Page(s.conversation_id, title, OTHER_CHAPTER, None, order=(1, 0, 0, 0))
            pages[s.conversation_id] = page

        ids = [i for i in _message_ids(s) if roles.get(i, (None,))[0] == s.conversation_id]
        is_you = bool(ids) and all(roles[i][1] == "user" for i in ids)
        speaker = None
        if s.speaker_name:
            speaker = casts.get(s.conversation_id, {}).get(s.speaker_name.lower()) or {
                "name": s.speaker_name, "role": "", "image_url": None, "initial": s.speaker_name[:1].upper()}
        page.entries.append(Entry(selection=s, page=page, speaker=speaker, is_you=is_you and speaker is None,
                                  message_id=min(ids) if ids else None))

    for page in pages.values():
        # In the order things happened in the chat; lines without a message by when they were saved.
        page.entries.sort(key=lambda e: (e.message_id is None, e.message_id or 0, e.created_at, e.id))
    ordered = sorted(pages.values(), key=lambda p: (p.order, -p.latest if p.exercise is None else 0, p.conversation_id))
    chapters = []
    for page in ordered:
        if not chapters or chapters[-1][0] != page.chapter:
            chapters.append((page.chapter, []))
        chapters[-1][1].append(page)
    return Notebook(pages=ordered, chapters=chapters)


def search_data(notebook, label):
    """What the contents page's search filters, in the browser: one item per
    entry. label(timestamp) formats its date."""
    return [{
        "id": e.id,
        "text": e.text,
        "thought": e.thought or "",
        "page": e.page.title,
        "chapter": e.page.chapter,
        "speaker": e.speaker["name"] if e.speaker else ("You" if e.is_you else ""),
        "image_url": e.speaker["image_url"] if e.speaker else None,
        "initial": e.speaker["initial"] if e.speaker else "",
        "saved": e.created_at,
        "date": label(e.created_at),
        "url": f"{e.page.url}#e-{e.id}",
        "chat_url": e.chat_url,
    } for e in notebook.entries]
