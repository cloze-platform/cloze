"""The redesigned participant pages (participant_ui = v2).

Server-rendered pages under templates/participant/. Home stays at /dashboard,
which hands participants here when the switch is on (see
conversations.user_dashboard). Today's JSON APIs are unchanged; these pages
call them.

Every page goes through participant_page: signed-in participants only, and
only while the switch is v2. Anyone else gets 404, so on a v1 instance the
pages don't exist.
"""

import json
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..models import Message, SafetyPlan, SavedSelection
from ..services import participant_nav
from ..services.greeting import greeting_for
from ..services.safety_info import DEFAULT_AGREEMENT, bold, safety_info
from ..utils.participant_ui import uses_v2
from ..utils.settings_resolution import get_effective_setting, get_provider_id_for_patient

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
        if request.endpoint not in OPEN_WHILE_CLOSED and _locked_out():
            return redirect(url_for("participant.closed"))
        return view(*args, **kwargs)
    return wrapped


def _locked_out():
    hours = participant_nav.opening_hours(get_provider_id_for_patient(current_user.id))
    return participant_nav.locked_out(hours)


def render_page(template, current=None, nav=None, **context):
    """Render a participant page with the menu's data. current names the menu
    item to mark: home, notebook, safety_plan, reports, exercises or help."""
    nav = nav or participant_nav.build(current_user)
    return render_template(template, nav=nav, current=current, **context)


def render_home():
    if _locked_out():
        return redirect(url_for("participant.closed"))
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
    return render_page(
        "participant/exercise.html", current="exercise", nav=nav, current_exercise=ex.id,
        phone_bar=False, exercise=ex, group=ex.group, messages=messages, state=state, next_exercise=next_ex,
        greeting=greeting_for(ex.id, current_user) if not messages else None,
        safety=safety_info(nav.provider_id) if state == "agree" else None, default_agreement=DEFAULT_AGREEMENT,
        notebook=participant_nav.notebook_entries(current_user.id) if nav.can_save else None,
    )


@participant_bp.route("/closed")
@participant_page
def closed():
    """The resting screen, while the study is closed in lock mode. Everything
    else redirects here, except Get help now and the safety plan."""
    hours = participant_nav.opening_hours(get_provider_id_for_patient(current_user.id))
    if not participant_nav.locked_out(hours):
        return redirect("/dashboard")
    nav = participant_nav.build(current_user)
    return render_template("participant/closed.html", nav=nav, hours=hours)


# Placeholders until their pages land (stage 1, pull request 3).
@participant_bp.route("/notebook")
@participant_page
def notebook():
    """The participant's saved lines, grouped by the exercise they came from,
    newest first, each with the participant's own note. 404 when the study
    doesn't let participants save, as the menu leaves it out then."""
    nav = participant_nav.build(current_user)
    if not nav.can_save:
        abort(404)
    groups = {}
    for selection, title in participant_nav.notebook_entries(current_user.id, limit=None):
        group = groups.setdefault(selection.conversation_id, {
            "title": title, "exercise": nav.exercise_for_conversation(selection.conversation_id), "lines": []})
        group["lines"].append(selection)
    return render_page("participant/notebook.html", current="notebook", nav=nav, groups=list(groups.values()),
                       note_limit=SavedSelection.NOTE_LIMIT)


@participant_bp.route("/safety-plan")
@participant_page
def safety_plan():
    """The participant's safety plan: their parts to add or change, and the
    care team's parts to read. Saving goes through today's
    /api/safety-plan/ endpoints (static/participant/safety-plan.js)."""
    nav = participant_nav.build(current_user)
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
        "participant/safety_plan.html", current="safety_plan", nav=nav, state=state,
        shown=shown.to_dict(for_patient=True) if shown else None,
        editing=editing.to_dict(for_patient=True) if editing else None,
        care=care.to_dict(for_patient=True) if care else None,
        approved_at=active.approved_at if active else None,
        sent_at=pending.updated_at if pending else None,
        allow_avoid=bool(get_effective_setting("allow_patient_anti_patterns", nav.provider_id, True)),
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
def reports(report_id=None):
    """The participant's reports: a list, and one open (the newest unless
    report_id says otherwise). Only their own summary reports from visible
    windows, the same rule as /api/reports/. Report content is today's,
    from the unified report generator. 404 when reports are off."""
    nav = participant_nav.build(current_user)
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
    return render_page("participant/reports.html", current="reports", nav=nav, reports=reports, report=report,
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
