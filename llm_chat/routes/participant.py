"""The redesigned participant pages (participant_ui = v2).

Server-rendered pages under templates/participant/. Home stays at /dashboard,
which hands participants here when the switch is on (see
conversations.user_dashboard). Today's JSON APIs are unchanged; these pages
call them.

Every page goes through participant_page: signed-in participants only, and
only while the switch is v2. Anyone else gets 404, so on a v1 instance the
pages don't exist. It builds the participant's menu data once per request
(participant_nav.build) and passes it to the page as nav.
"""

import json
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Message, SafetyPlan, SavedSelection
from ..services import participant_nav
from ..services import notebook as notebook_layout
from ..services.greeting import greeting_for
from ..services.speakers import cast_for_template, reply_parts
from ..services.guides import guide_for_template
from ..services import need_help as need_help_content
from ..services.safety_info import DEFAULT_AGREEMENT, bold, safety_info
from ..utils.access_hours import DEFAULT_TZ
from ..utils.participant_ui import uses_v2

participant_bp = Blueprint("participant", __name__, url_prefix="")


# Reachable while the study is closed in lock mode: safety content, and the
# resting screen itself.
OPEN_WHILE_CLOSED = {"participant.help_page", "participant.safety_plan", "participant.closed"}


def participant_page(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_patient() or not uses_v2():
            abort(404)
        try:
            nav = participant_nav.build(current_user)
        except Exception:
            # Get help now must still show its crisis lines (see help_page).
            if request.endpoint != "participant.help_page":
                raise
            current_app.logger.exception("Get help now: the menu's data didn't load")
            db.session.rollback()
            nav = None
        if (nav is not None and request.endpoint not in OPEN_WHILE_CLOSED
                and participant_nav.locked_out(nav.opening_hours)):
            return redirect(url_for("participant.closed"))
        return view(*args, nav=nav, **kwargs)
    return wrapped


def render_page(template, nav, current=None, **context):
    """Render a participant page with the menu's data. current names the menu
    item to mark: home, notebook, safety_plan, reports, exercises or help."""
    return render_template(template, nav=nav, current=current, **context)


def render_home():
    """Home, for /dashboard (conversations.user_dashboard), which has already
    checked the user and the switch."""
    nav = participant_nav.build(current_user)
    if participant_nav.locked_out(nav.opening_hours):
        return redirect(url_for("participant.closed"))
    return render_page("participant/home.html", nav, current="home")


# ── Pages ──────────────────────────────────────────────────────

@participant_bp.route("/help")
@participant_page
def help_page(nav):
    """Get help now as a page: for phones without JavaScript, and as the
    link's target everywhere (the menu opens it as a dialog when it can).
    If the menu's data can't be loaded (nav is None), the page still shows the
    crisis lines, without the menu."""
    return render_page("participant/help.html", nav, current="help")


@participant_bp.route("/exercises")
@participant_page
def exercises(nav):
    """Every group and exercise. The phone's Exercises tab; on a computer the
    menu shows the same list."""
    return render_page("participant/exercises.html", nav, current="exercises")


@participant_bp.route("/exercise/<int:conversation_id>")
@participant_page
def exercise(conversation_id, nav):
    """An exercise the participant has started (or opened): only their own
    exercise's conversation, in a visible window. Anything else is 404."""
    ex = nav.exercise_for_conversation(conversation_id)
    if ex is None:
        abort(404)
    messages = ex.conversation.messages.order_by(Message.timestamp).all()
    return _render_exercise(nav, ex, messages)


@participant_bp.route("/exercise/template/<int:template_id>")
@participant_page
def exercise_template(template_id, nav):
    """An exercise not started yet. Agreeing to the safety information starts
    its conversation (static/participant/exercise.js)."""
    ex = nav.exercise_for_template(template_id)
    if ex is None:
        abort(404)
    if ex.conversation is not None:
        return redirect(url_for("participant.exercise", conversation_id=ex.conversation_id))
    return _render_exercise(nav, ex, [])


def exercise_state(nav, ex):
    """What the bottom of the exercise screen shows:
      finished      the conversation has ended (with its reason)
      locked_plan   not started, and a required safety plan isn't approved
      upcoming      its group hasn't opened yet
      closed        its group closed before it was started
      resting       outside opening hours (read-only mode): reading only
      agree         the safety information, before the first message
      open          replying"""
    if ex.state == participant_nav.FINISHED:
        return "finished"
    if nav.locked(ex) == "safety_plan":
        return "locked_plan"
    if not ex.group.is_open:
        return "upcoming" if ex.group.is_upcoming else "closed"
    if nav.opening_hours.get("enabled") and not nav.opening_hours.get("open"):
        return "resting"
    if ex.conversation is None or not ex.conversation.consent_provided:
        return "agree"
    return "open"


def _render_exercise(nav, ex, messages):
    state = exercise_state(nav, ex)
    later = ex.group.exercises[ex.group.exercises.index(ex) + 1:]
    next_ex = next((e for e in later if e.state != participant_nav.FINISHED and not nav.locked(e)), None)
    # In a chat with a cast, each reply shows as the parts its speakers say.
    cast, main = cast_for_template(ex.template, current_user)
    parts = {m.id: reply_parts(m.content, cast, main, current_user)
             for m in messages if m.role == "assistant"} if cast else {}
    guide, open_guide, _ = guide_for_template(ex.template, current_user)
    help_box = need_help_content.for_chat(ex.template, current_user, has_guide=guide is not None) if state == "open" else None
    return render_page(
        "participant/exercise.html", nav, current="exercise", current_exercise=ex.id,
        phone_bar=False, exercise=ex, group=ex.group, messages=messages, state=state, next_exercise=next_ex,
        reply_parts=parts, writer=main.name if main else None, guide=guide, open_guide=open_guide,
        need_help=help_box,
        greeting=greeting_for(ex.id, current_user) if not messages else None,
        safety=safety_info(nav.provider_id) if state == "agree" else None, default_agreement=DEFAULT_AGREEMENT,
        # The panel's Notebook: this exercise's page only.
        notebook=([(s, ex.title) for s, _ in participant_nav.notebook_entries(current_user.id, limit=None)
                   if ex.conversation_id and s.conversation_id == ex.conversation_id]
                  if nav.can_save else None),
    )


@participant_bp.route("/closed")
@participant_page
def closed(nav):
    """The resting screen, while the study is closed in lock mode. Everything
    else redirects here, except Get help now and the safety plan."""
    if not participant_nav.locked_out(nav.opening_hours):
        return redirect("/dashboard")
    return render_template("participant/closed.html", nav=nav, hours=nav.opening_hours)


@participant_bp.route("/notebook")
@participant_page
def notebook(nav):
    """The notebook's contents: each exercise with something saved is a page,
    under its group, in the order of the Exercises menu. Search runs in the
    browser over every entry. 404 when the study doesn't let participants
    save, as the menu leaves it out then."""
    if not nav.can_save:
        abort(404)
    book = notebook_layout.build(nav, current_user)
    return render_page("participant/notebook.html", nav, current="notebook", book=book,
                       search_data=notebook_layout.search_data(book, lambda t: p_saved(t, nav.timezone, nav.now)))


@participant_bp.route("/notebook/page/<int:conversation_id>")
@participant_page
def notebook_page(conversation_id, nav):
    """One page of the notebook: what was saved in one exercise, in the order
    it happened in the chat, each line with the participant's thought."""
    if not nav.can_save:
        abort(404)
    book = notebook_layout.build(nav, current_user)
    page = book.page_for(conversation_id)
    if page is None:
        abort(404)
    previous, following = book.neighbours(page)
    return render_page("participant/notebook_page.html", nav, current="notebook", book=book, page=page,
                       previous=previous, following=following, note_limit=SavedSelection.NOTE_LIMIT)


@participant_bp.route("/safety-plan")
@participant_page
def safety_plan(nav):
    """The participant's safety plan: their parts to add or change, and the
    care team's parts to read. Saving goes through today's
    /api/safety-plan/ endpoints (static/participant/safety-plan.js)."""
    # One of each status; the oldest wins, as in /api/safety-plan/.
    plans = {p.status: p for p in SafetyPlan.query.filter(
        SafetyPlan.patient_id == current_user.id,
        SafetyPlan.status.in_(("active", "pending_review", "draft"))).order_by(SafetyPlan.id.desc())}
    active, pending, draft = plans.get("active"), plans.get("pending_review"), plans.get("draft")
    state = nav.safety_plan.state
    # What the page shows read-only, and what the form starts from.
    shown = {"approved": active, "change_waiting": active, "waiting": pending}.get(state)
    editing = {"your_turn": draft, "approved": active, "change_waiting": pending}.get(state)
    care = (active or pending or draft)
    return render_page(
        "participant/safety_plan.html", nav, current="safety_plan", state=state,
        shown=shown.to_dict(for_patient=True) if shown else None,
        editing=editing.to_dict(for_patient=True) if editing else None,
        care=care.to_dict(for_patient=True) if care else None,
        approved_at=active.approved_at if active else None,
        sent_at=pending.updated_at if pending else None,
        allow_avoid=bool(nav.settings.get("allow_patient_anti_patterns", True)),
        ratings=PLAN_RATINGS,
    )


# The 1-5 scales the safety plan form asks about (the prompt reads them;
# see prompts/composer.py). Labels as today's form, in plain words.
PLAN_RATINGS = {
    "severity": ["Mild", "Mild to moderate", "Moderate", "Moderate to severe", "Severe"],
    "effectiveness": ["A little", "Somewhat", "Moderately", "A lot", "Very much"],
    "comfort": ["Very low", "Low", "Moderate", "High", "Very high"],
}


@participant_bp.route("/reports")
@participant_bp.route("/reports/<int:report_id>")
@participant_page
def reports(nav, report_id=None):
    """The participant's reports: a list, and one open (the newest unless
    report_id says otherwise). Only their own summary reports from visible
    windows, the same rule as /api/reports/. Report content is today's,
    from the unified report generator. 404 when reports are off."""
    if not nav.reports_enabled:
        abort(404)
    reports = participant_nav.participant_reports_query(current_user.id).all()
    if report_id is None:
        report = reports[0] if reports else None
    else:
        report = next((r for r in reports if r.id == report_id), None)
        if report is None:
            abort(404)
    html = None
    if report is not None:
        from report.generator import UnifiedReportGenerator
        html = UnifiedReportGenerator(report.window_id).render_html(json.loads(report.report_data or "{}"))
    return render_page("participant/reports.html", nav, current="reports", reports=reports, report=report,
                       report_html=html, groups={g.id: g for g in nav.groups}, preparing=nav.preparing_reports)


# ── Template helpers ──────────────────────────────────────────

@participant_bp.app_template_global()
def exercise_url(exercise):
    """Where an exercise opens: its conversation, or the template when it
    hasn't been started (the first message starts it)."""
    if exercise.conversation_id:
        return url_for("participant.exercise", conversation_id=exercise.conversation_id)
    return url_for("participant.exercise_template", template_id=exercise.id)


def _local(timestamp, tz_name):
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_TZ)
    return datetime.fromtimestamp(timestamp, tz)


@participant_bp.app_template_filter("p_day")
def p_day(timestamp, tz_name):
    """'Mon 3 Dec' in the study's timezone."""
    d = _local(timestamp, tz_name)
    return f"{d:%a} {d.day} {d:%b}"


@participant_bp.app_template_filter("p_date")
def p_date(timestamp, tz_name):
    """'3 Dec' in the study's timezone."""
    d = _local(timestamp, tz_name)
    return f"{d.day} {d:%b}"


@participant_bp.app_template_filter("p_saved")
def p_saved(timestamp, tz_name, now):
    """'Today', 'Yesterday', or 'Mon 23 Nov', in the study's timezone."""
    then, today = _local(timestamp, tz_name).date(), _local(now, tz_name).date()
    if then == today:
        return "Today"
    if (today - then).days == 1:
        return "Yesterday"
    return p_day(timestamp, tz_name)


@participant_bp.app_template_filter("p_when")
def p_when(timestamp, tz_name):
    """'Fri 5:00 pm' in the study's timezone."""
    d = _local(timestamp, tz_name)
    return f"{d:%a} {d.hour % 12 or 12}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


@participant_bp.app_template_filter("p_long")
def p_long(timestamp, tz_name):
    """'Friday, 14 March' in the study's timezone."""
    d = _local(timestamp, tz_name)
    return f"{d:%A}, {d.day} {d:%B}"


@participant_bp.app_template_filter("p_bold")
def p_bold(text):
    return bold(text)


@participant_bp.app_template_test("list_item")
def is_list_item(line):
    """A '- ' line in a safety information block."""
    return line.strip().startswith("-")


@participant_bp.app_template_filter("p_ago")
def p_ago(timestamp, tz_name, now):
    """'Just now', '5 min ago', 'Today 3:10 pm', 'Yesterday', or '3 Dec'."""
    seconds = now - timestamp
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    then, today = _local(timestamp, tz_name).date(), _local(now, tz_name).date()
    if then == today:
        return "Today " + p_when(timestamp, tz_name).split(" ", 1)[1]
    if (today - then).days == 1:
        return "Yesterday"
    return p_date(timestamp, tz_name)


@participant_bp.app_template_filter("p_iso")
def p_iso(timestamp):
    return datetime.fromtimestamp(timestamp, ZoneInfo("UTC")).isoformat()
