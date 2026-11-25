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

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from ..services import participant_nav
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


def render_page(template, current=None, **context):
    """Render a participant page with the menu's data. current names the menu
    item to mark: home, notebook, safety_plan, reports, exercises or help."""
    nav = participant_nav.build(current_user)
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
        return f"/exercise/{exercise.conversation_id}"
    return f"/exercise/template/{exercise.id}"


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


@participant_bp.app_template_filter("p_iso")
def p_iso(timestamp):
    return datetime.fromtimestamp(timestamp, ZoneInfo("UTC")).isoformat()
