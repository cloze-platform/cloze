"""The redesigned participant pages (participant_ui = v2).

Server-rendered pages under templates/participant/. Home stays at /dashboard,
which hands participants here when the switch is on (see
conversations.user_dashboard). Today's JSON APIs are unchanged; these pages
call them.

Every page goes through participant_page: signed-in participants only, and
only while the switch is v2. Anyone else gets 404, so on a v1 instance the
pages don't exist.
"""

from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..models import Message
from ..services import participant_nav
from ..services.greeting import greeting_for
from ..services.safety_info import DEFAULT_AGREEMENT, bold, safety_info
from ..utils.participant_ui import uses_v2

participant_bp = Blueprint("participant", __name__, url_prefix="")


def participant_page(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_patient() or not uses_v2():
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def render_page(template, current=None, nav=None, **context):
    """Render a participant page with the menu's data. current names the menu
    item to mark: home, notebook, safety_plan, reports, exercises or help."""
    nav = nav or participant_nav.build(current_user)
    return render_template(template, nav=nav, current=current, **context)


def render_home():
    return render_page("participant/home.html", current="home")


# ── Pages ──────────────────────────────────────────────────────

@participant_bp.route("/help")
@participant_page
def help_page():
    """Get help now as a page: for phones without JavaScript, and as the
    link's target everywhere (the menu opens it as a dialog when it can)."""
    return render_page("participant/help.html", current="help")


@participant_bp.route("/exercises")
@participant_page
def exercises():
    """Every group and exercise. The phone's Exercises tab; on a computer the
    menu shows the same list."""
    return render_page("participant/exercises.html", current="exercises")


@participant_bp.route("/exercise/<int:conversation_id>")
@participant_page
def exercise(conversation_id):
    """An exercise the participant has started (or opened): only their own
    exercise's conversation, in a visible window. Anything else is 404."""
    nav = participant_nav.build(current_user)
    ex = nav.exercise_for_conversation(conversation_id)
    if ex is None:
        abort(404)
    messages = ex.conversation.messages.order_by(Message.timestamp).all()
    return _render_exercise(nav, ex, messages)


@participant_bp.route("/exercise/template/<int:template_id>")
@participant_page
def exercise_template(template_id):
    """An exercise not started yet. Agreeing to the safety information starts
    its conversation (static/participant/exercise.js)."""
    nav = participant_nav.build(current_user)
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
      agree         the safety information, before the first message
      open          replying"""
    if ex.state == participant_nav.FINISHED:
        return "finished"
    if nav.locked(ex) == "safety_plan":
        return "locked_plan"
    if not ex.group.is_open:
        return "upcoming" if ex.group.is_upcoming else "closed"
    if ex.conversation is None or not ex.conversation.consent_provided:
        return "agree"
    return "open"


def _render_exercise(nav, ex, messages):
    state = exercise_state(nav, ex)
    later = ex.group.exercises[ex.group.exercises.index(ex) + 1:]
    next_ex = next((e for e in later if e.state != participant_nav.FINISHED and not nav.locked(e)), None)
    return render_page(
        "participant/exercise.html", current="exercise", nav=nav, current_exercise=ex.id,
        phone_bar=False, exercise=ex, group=ex.group, messages=messages, state=state, next_exercise=next_ex,
        greeting=greeting_for(ex.id, current_user) if not messages else None,
        safety=safety_info(nav.provider_id) if state == "agree" else None, default_agreement=DEFAULT_AGREEMENT,
    )


# Placeholders until their pages land (stage 1, pull request 3).
@participant_bp.route("/notebook")
@participant_page
def notebook():
    return render_page("participant/placeholder.html", current="notebook", heading="Notebook")


@participant_bp.route("/safety-plan")
@participant_page
def safety_plan():
    return render_page("participant/placeholder.html", current="safety_plan", heading="Safety plan")


@participant_bp.route("/reports")
@participant_page
def reports():
    return render_page("participant/placeholder.html", current="reports", heading="Reports")


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
        tz = ZoneInfo("America/New_York")
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


@participant_bp.app_template_filter("p_iso")
def p_iso(timestamp):
    return datetime.fromtimestamp(timestamp, ZoneInfo("UTC")).isoformat()
