"""What a participant can see: one place for the rules.

build(user) returns the participant's groups (chat windows) and exercises
(chat templates) with their state, the conversations they can open, and the
study-level state the menu and Home need: the safety plan, saving to the
notebook, reports and opening hours.

The redesigned pages render from it, and today's /api/windows/current and
/api/conversations are built from it too, so the two interfaces can't
disagree about what a participant sees. Change visibility rules here, not in
the routes.

The main rules:
- Hidden windows don't exist for the participant. Withdrawing from a study
  hides the windows that haven't ended, so they disappear too.
- Hidden templates don't exist either.
- An exercise's conversation is the participant's first conversation for that
  window and template.
- An exercise is Finished when its conversation has ended (ended_at; see
  services/conversation_end.py), Started when it has messages, otherwise Not
  started. Reading a conversation whose window has ended records it as ended.
"""

import json
import time
from dataclasses import dataclass, field
from functools import cached_property

from sqlalchemy import case, func

from ..extensions import db
from ..models import ChatTemplate, ChatWindow, Conversation, Message, Report, SafetyPlan, SavedSelection
from ..utils.settings_resolution import get_effective_setting, get_provider_id_for_patient
from .conversation_end import stamp_window_closed

NOT_STARTED, STARTED, FINISHED = "not_started", "started", "finished"
TURN_LIMIT, WINDOW_CLOSED = "turn_limit", "window_closed"

OPEN, UPCOMING = "active", "scheduled"           # ChatWindow.compute_status values
CLOSED = ("generating_report", "report_ready")


@dataclass
class Exercise:
    """One chat template in a group, with the participant's conversation if any."""
    template: ChatTemplate
    group: "Group" = field(repr=False)
    conversation: Conversation | None = None
    message_count: int = 0
    turns_used: int = 0
    max_turns: int | None = None

    @property
    def id(self):
        return self.template.id

    @property
    def title(self):
        return self.template.title

    @property
    def conversation_id(self):
        return self.conversation.id if self.conversation else None

    @property
    def turns_left(self):
        return max(0, self.max_turns - self.turns_used) if self.max_turns else None

    @property
    def end_reason(self):
        """Why a finished exercise ended, or None. The recorded reason when
        there is one (Conversation.end_reason). Otherwise the turn count: a
        conversation already at the limit before reasons were recorded."""
        if self.conversation is None:
            return None
        if self.conversation.ended_at is not None:
            return self.conversation.end_reason
        if self.max_turns and self.turns_used >= self.max_turns:
            return TURN_LIMIT
        if self.group.is_closed:
            return WINDOW_CLOSED
        return None

    @property
    def state(self):
        if self.end_reason:
            return FINISHED
        return STARTED if self.message_count else NOT_STARTED


@dataclass
class Group:
    """A chat window: the exercises the participant has for one phase or cycle."""
    window: ChatWindow
    status: str
    exercises: list = field(default_factory=list)

    @property
    def id(self):
        return self.window.id

    @property
    def name(self):
        return self.window.phase_label or self.window.flow_name or self.window.title

    @property
    def is_open(self):
        return self.status == OPEN

    @property
    def is_upcoming(self):
        return self.status == UPCOMING

    @property
    def is_closed(self):
        return self.status in CLOSED

    @property
    def opens_at(self):
        return self.window.start_date

    @property
    def closes_at(self):
        return self.window.end_date

    def count(self, state):
        return sum(1 for e in self.exercises if e.state == state)


@dataclass
class Chat:
    """A conversation the participant can see, as /api/conversations lists it."""
    conversation: Conversation
    window: ChatWindow | None
    status: str | None
    message_count: int


@dataclass
class SafetyPlanState:
    """The participant's safety plan, as their pages show it.

    state is one of:
      off             the study doesn't use safety plans
      none            the research team hasn't started one yet
      your_turn       a draft is waiting for the participant's sections
      waiting         submitted for the first time, waiting for review
      approved        active, nothing pending
      change_waiting  active, with changes waiting for review
    """
    required: bool
    state: str
    sections_done: int = 0     # of the participant's four sections, in the draft
    SECTIONS = 4

    @property
    def blocks_starting(self):
        """Exercises can't be started until a required plan is approved (the
        server enforces this in start_conversation_from_template)."""
        return self.required and self.state not in ("approved", "change_waiting")

    @property
    def needs_participant(self):
        return self.state == "your_turn"


@dataclass
class Nav:
    user: object
    now: float
    provider_id: int | None
    groups: list           # every visible window, oldest first
    chats: list            # every conversation the participant can see, newest first
    max_turns: int | None

    # ── Groups and exercises ──

    @property
    def open_groups(self):
        return [g for g in self.groups if g.is_open]

    @property
    def upcoming_groups(self):
        return sorted((g for g in self.groups if g.is_upcoming), key=lambda g: (g.opens_at, g.id))

    @property
    def menu_groups(self):
        """Groups for the menu and Home: in the order they open."""
        return sorted(self.groups, key=lambda g: (g.opens_at, g.id))

    @property
    def exercises(self):
        return [e for g in self.groups for e in g.exercises]

    def exercise_for_template(self, template_id):
        return next((e for e in self.exercises if e.id == template_id), None)

    def exercise_for_conversation(self, conversation_id):
        return next((e for e in self.exercises if e.conversation_id == conversation_id), None)

    def focus_group(self, current_exercise=None):
        """The group to open in the menu: the one holding the current exercise;
        otherwise the open group with the most recently used exercise in
        progress; otherwise the first open group with anything left to do."""
        if current_exercise:
            return next((g for g in self.groups if any(e.id == current_exercise for e in g.exercises)), None)
        started = [e for g in self.open_groups for e in g.exercises if e.state == STARTED]
        if started:
            return max(started, key=lambda e: (e.conversation.updated_at or 0, e.conversation.id)).group
        return next((g for g in self.menu_groups
                     if g.is_open and any(e.state != FINISHED for e in g.exercises)), None)

    def locked(self, exercise):
        """Why the participant can't start this exercise now, or None."""
        if exercise.conversation is not None:
            return None
        if not exercise.group.is_open:
            return "window"
        if self.safety_plan.blocks_starting:
            return "safety_plan"
        return None

    # ── Study-level state (loaded when first used) ──

    @cached_property
    def safety_plan(self):
        return safety_plan_state(self.user.id, self.provider_id)

    @cached_property
    def can_save(self):
        return bool(get_effective_setting("users_can_save_selections", self.provider_id, True))

    @cached_property
    def notebook_count(self):
        return SavedSelection.query.filter_by(user_id=self.user.id).count()

    @cached_property
    def reports_enabled(self):
        return bool(get_effective_setting("enable_nlp_report", self.provider_id, True))

    @cached_property
    def report_count(self):
        return participant_reports_query(self.user.id).count() if self.reports_enabled else 0

    @cached_property
    def opening_hours(self):
        return opening_hours(self.provider_id)

    @cached_property
    def active_plan(self):
        """The approved safety plan, if any: Get help now shows its care team."""
        return SafetyPlan.get_active_plan(self.user.id)

    @cached_property
    def timezone(self):
        """The study's timezone, for dates on the participant's pages."""
        return get_effective_setting("access_hours_timezone", self.provider_id, "America/New_York")


def build(user, now=None):
    """Everything a participant's pages show about their study, as of now."""
    now = time.time() if now is None else now
    provider_id = get_provider_id_for_patient(user.id) if user.is_patient() else None
    max_turns = get_effective_setting("max_turns_per_conversation", provider_id) if user.is_patient() else None

    windows = (ChatWindow.query.filter_by(patient_id=user.id, visible=True)
               .order_by(ChatWindow.id).all())
    conversations = user.conversations.order_by(Conversation.updated_at.desc()).all()

    # Every conversation's window, hidden ones included. A conversation whose
    # window has ended is recorded as finished the first time it's seen.
    windows_by_id = {w.id: w for w in windows}
    missing = {c.window_id for c in conversations if c.window_id and c.window_id not in windows_by_id}
    if missing:
        windows_by_id.update({w.id: w for w in ChatWindow.query.filter(ChatWindow.id.in_(missing))})
    if [c for c in conversations if stamp_window_closed(c, windows_by_id.get(c.window_id), now)]:
        db.session.commit()

    templates = (ChatTemplate.query
                 .filter(ChatTemplate.window_id.in_([w.id for w in windows]), ChatTemplate.visible.is_(True))
                 .order_by(ChatTemplate.window_id, ChatTemplate.order_index, ChatTemplate.id).all()
                 if windows else [])
    counts = _message_counts([c.id for c in conversations])

    # An exercise's conversation: the first one for its window and template.
    by_exercise = {}
    for c in sorted(conversations, key=lambda c: c.id):
        if c.window_id and c.template_id:
            by_exercise.setdefault((c.window_id, c.template_id), c)

    groups = {w.id: Group(window=w, status=w.compute_status(now)) for w in windows}
    for t in templates:
        group = groups[t.window_id]
        conv = by_exercise.get((t.window_id, t.id))
        total, user_turns = counts.get(conv.id, (0, 0)) if conv else (0, 0)
        group.exercises.append(Exercise(template=t, group=group, conversation=conv, message_count=total,
                                        turns_used=user_turns, max_turns=max_turns))

    return Nav(user=user, now=now, provider_id=provider_id, groups=list(groups.values()),
               chats=_visible_chats(conversations, windows_by_id, counts, now), max_turns=max_turns)


def _message_counts(conversation_ids):
    """{conversation_id: (messages, participant messages)}."""
    if not conversation_ids:
        return {}
    rows = (db.session.query(Message.conversation_id, func.count(Message.id),
                             func.sum(case((Message.role == "user", 1), else_=0)))
            .filter(Message.conversation_id.in_(conversation_ids))
            .group_by(Message.conversation_id).all())
    return {cid: (total, int(user_turns or 0)) for cid, total, user_turns in rows}


def _visible_chats(conversations, windows, counts, now):
    """The participant's conversations, minus those in hidden windows and
    hidden ones with no messages. A conversation whose window was deleted
    keeps showing, without window details."""
    chats = []
    for c in conversations:
        window = windows.get(c.window_id)
        if window is not None and not window.visible:
            continue
        total = counts.get(c.id, (0, 0))[0]
        if total == 0 and not c.visible:
            continue
        chats.append(Chat(conversation=c, window=window, status=window.compute_status(now) if window else None,
                          message_count=total))
    return chats


def safety_plan_state(patient_id, provider_id):
    required = bool(get_effective_setting("require_safety_plan", provider_id, True))
    if not required:
        return SafetyPlanState(required=False, state="off")
    plans = SafetyPlan.query.filter(SafetyPlan.patient_id == patient_id,
                                    SafetyPlan.status.in_(("active", "pending_review", "draft"))).all()
    has = {p.status for p in plans}
    active, pending, draft = "active" in has, "pending_review" in has, "draft" in has
    draft_plan = next((p for p in plans if p.status == "draft"), None)
    sections_done = sum(1 for section in (draft_plan.get_warning_signs(), draft_plan.get_coping_strategies(),
                                          draft_plan.get_support_network(), draft_plan.get_reasons_for_living())
                        if section) if draft_plan else 0
    if not (active or pending or draft):
        state = "none"
    elif draft and not active:
        state = "your_turn"
    elif active:
        state = "change_waiting" if pending else "approved"
    else:
        state = "waiting"
    return SafetyPlanState(required=True, state=state, sections_done=sections_done)


def notebook_entries(user_id, limit=50):
    """The participant's saved lines, newest first, each with the title of the
    conversation it came from: [(SavedSelection, title)]. limit=None for all."""
    query = (SavedSelection.query.filter_by(user_id=user_id)
             .order_by(SavedSelection.created_at.desc(), SavedSelection.id.desc()))
    selections = (query.limit(limit) if limit else query).all()
    ids = {s.conversation_id for s in selections}
    titles = dict(db.session.query(Conversation.id, Conversation.title).filter(Conversation.id.in_(ids)).all()) if ids else {}
    return [(s, titles.get(s.conversation_id) or "An exercise") for s in selections]


def participant_reports_query(patient_id):
    """The participant's own reports from visible windows, newest first. One
    per window: the summary report, not the detailed one."""
    return (Report.query.join(ChatWindow)
            .filter(Report.patient_id == patient_id, ChatWindow.visible.is_(True),
                    Report.report_type.in_(("summary", "default")))
            .order_by(Report.generated_at.desc()))


LOCK, READ_ONLY = "lock", "read_only"


def opening_hours(provider_id):
    """The study's opening hours now: {"enabled": False}, or enabled with
    open, schedule, reopen and reopens_at (see utils.access_hours.window_status)
    and mode: lock or read_only (ProviderFeatureFlags.access_hours_mode)."""
    if not get_effective_setting("access_hours_enabled", provider_id, False):
        return {"enabled": False}
    start = get_effective_setting("access_hours_start", provider_id)
    end = get_effective_setting("access_hours_end", provider_id)
    if not start or not end:
        return {"enabled": False}
    tz = get_effective_setting("access_hours_timezone", provider_id, "America/New_York")
    days_raw = get_effective_setting("access_hours_days", provider_id)
    try:
        days = json.loads(days_raw) if days_raw else None
    except (TypeError, ValueError):
        days = None

    from ..utils.access_hours import window_status
    status = window_status(start, end, tz, days)
    status["enabled"] = True
    mode = get_effective_setting("access_hours_mode", provider_id, LOCK)
    status["mode"] = READ_ONLY if mode == READ_ONLY else LOCK
    return status


def locked_out(hours):
    """Closed, with the study set to show the resting screen instead of the site."""
    return bool(hours.get("enabled") and not hours.get("open") and hours.get("mode") == LOCK)
