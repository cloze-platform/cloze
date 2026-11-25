"""participant_nav.build: what a participant can see, shared by the new pages
and today's /api/windows/current and /api/conversations.

The snapshot test pins both APIs' responses for a seeded study. It was
recorded from the code before they moved onto participant_nav, so the
refactor can't change what today's dashboard shows. Re-record only for an
intended change:  CLOZE_UPDATE_SNAPSHOTS=1 pytest tests/test_participant_nav.py
"""

import json
import os
from pathlib import Path

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import AdminSettings, ProviderFeatureFlags, Report, SafetyPlan, SavedSelection

SNAPSHOT = Path(__file__).parent / "snapshots" / "participant_apis.json"


# ── Today's APIs must not change ───────────────────────────────

def _responses(client):
    return {
        "windows_current": client.get("/api/windows/current").get_json(),
        "conversations": client.get("/api/conversations").get_json(),
    }


def test_window_and_conversation_apis_match_the_snapshot(study, login_as):
    got = _responses(login_as(study["patient"]))
    if os.environ.get("CLOZE_UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(SNAPSHOT.read_text())


def test_other_participants_see_none_of_it(study, login_as):
    assert login_as(study["other"]).get("/api/windows/current").get_json()[0]["title"] == "Someone else's week"
    titles = [c["title"] for c in login_as(study["other"]).get("/api/conversations").get_json()]
    assert titles == ["Not yours"]


# ── build() ────────────────────────────────────────────────────

from llm_chat.services import participant_nav as nav_mod  # noqa: E402


def _build(study):
    return nav_mod.build(study["patient"])


def test_groups_are_the_visible_windows_named_by_phase_or_flow(study):
    nav = _build(study)
    assert [g.name for g in nav.groups] == ["Week 1", "Week 2", "Intro", "Characters", "Pilot"]
    assert [g.name for g in nav.menu_groups] == ["Pilot", "Characters", "Intro", "Week 1", "Week 2"]
    assert [g.name for g in nav.open_groups] == ["Week 1", "Characters"]
    assert [g.name for g in nav.upcoming_groups] == ["Week 2"]
    assert {g.name for g in nav.groups if g.is_closed} == {"Intro", "Pilot"}


def test_a_window_without_flow_or_phase_is_named_by_its_title(study):
    study["week1"].phase_label = None
    study["week1"].flow_name = None
    _db.session.commit()
    assert _build(study).groups[0].name == "Week 1"


def test_exercise_states(study):
    nav = _build(study)
    state = {e.title: (e.state, e.end_reason) for e in nav.exercises}
    assert state == {
        "Thought records": ("started", None),
        "Check-in": ("not_started", None),
        "Behavioural activation": ("not_started", None),
        "Welcome": ("finished", "window_closed"),
        "Never started": ("not_started", None),
        "Sky": ("not_started", None),
        "Star": ("not_started", None),      # a conversation, but nothing sent yet
        "Pilot chat": ("finished", "window_closed"),
    }
    assert nav.exercise_for_template(study["star"].id).conversation_id == study["star_conv"].id
    assert nav.exercise_for_conversation(study["thoughts_conv"].id).title == "Thought records"
    assert "Hidden chat" not in state and "Secret" not in state


def test_turn_limit_finishes_an_exercise(study, db):
    db.session.add(AdminSettings(setting_name="max_turns_per_conversation", setting_value="2"))
    db.session.commit()
    ex = _build(study).exercise_for_template(study["thoughts"].id)   # 4 messages, 2 from the participant
    assert (ex.turns_used, ex.turns_left, ex.state, ex.end_reason) == (2, 0, "finished", "turn_limit")


def test_turns_left_follow_the_researchers_setting(study, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=10))
    db.session.commit()
    nav = _build(study)
    assert nav.exercise_for_template(study["thoughts"].id).turns_left == 8
    assert nav.exercise_for_template(study["sky"].id).turns_left == 10


def test_no_turn_limit_means_no_turns_left(study):
    assert _build(study).exercise_for_template(study["thoughts"].id).turns_left is None


def test_progress_counts(study):
    week1 = _build(study).groups[0]
    assert (week1.count("started"), week1.count("finished"), week1.count("not_started")) == (1, 0, 1)


def test_withdrawing_hides_the_windows_that_have_not_ended(study, db):
    study["week1"].visible = False     # what _hide_unfinished_windows does
    db.session.commit()
    nav = _build(study)
    assert "Week 1" not in [g.name for g in nav.groups]
    assert study["thoughts_conv"].id not in [c.conversation.id for c in nav.chats]


# ── Safety plan ──

@pytest.mark.parametrize("statuses, state, blocks", [
    ([], "none", True),
    (["draft"], "your_turn", True),
    (["pending_review"], "waiting", True),
    (["draft", "pending_review"], "your_turn", True),
    (["active"], "approved", False),
    (["active", "draft"], "approved", False),
    (["active", "pending_review"], "change_waiting", False),
])
def test_safety_plan_states(study, db, statuses, state, blocks):
    for status in statuses:
        db.session.add(SafetyPlan(patient_id=study["patient"].id, status=status))
    db.session.commit()
    nav = _build(study)
    assert (nav.safety_plan.state, nav.safety_plan.blocks_starting) == (state, blocks)
    check_in = nav.exercise_for_template(study["checkin"].id)
    assert nav.locked(check_in) == ("safety_plan" if blocks else None)


def test_safety_plan_off_never_blocks(study, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, require_safety_plan=False))
    db.session.commit()
    nav = _build(study)
    assert (nav.safety_plan.state, nav.safety_plan.blocks_starting) == ("off", False)
    assert nav.locked(nav.exercise_for_template(study["checkin"].id)) is None


def test_started_exercises_and_closed_windows_lock_for_their_own_reasons(study):
    nav = _build(study)
    assert nav.locked(nav.exercise_for_template(study["thoughts"].id)) is None       # already started
    assert nav.locked(nav.exercise_for_template(study["activation"].id)) == "window"  # not open yet


def test_locked_matches_what_the_server_allows(study, login_as, db):
    """The page's lock and start_conversation_from_template agree."""
    nav = _build(study)
    client = login_as(study["patient"])
    for template_id in (study["checkin"].id, study["activation"].id):
        resp = client.post("/api/windows/start_conversation", json={"template_id": template_id})
        assert resp.status_code == 403
        assert nav.locked(nav.exercise_for_template(template_id)) is not None
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="active"))
    db.session.commit()
    nav = _build(study)
    assert nav.locked(nav.exercise_for_template(study["checkin"].id)) is None
    assert login_as(study["patient"]).post("/api/windows/start_conversation",
                                           json={"template_id": study["checkin"].id}).status_code == 200


# ── Notebook, reports, opening hours ──

def test_saving_and_notebook(study, db):
    db.session.add(SavedSelection(user_id=study["patient"].id, conversation_id=study["thoughts_conv"].id,
                                  selection_text="a line"))
    db.session.commit()
    nav = _build(study)
    assert (nav.can_save, nav.notebook_count) == (True, 1)
    db.session.add(AdminSettings(setting_name="users_can_save_selections", setting_value="false"))
    db.session.commit()
    assert _build(study).can_save is False


def _report(study, window, report_type="summary"):
    _db.session.add(Report(window_id=window.id, patient_id=study["patient"].id,
                           provider_id=study["provider"].id, report_type=report_type, report_data="{}"))
    _db.session.commit()


def test_reports_count_only_the_participants_summaries(study, login_as):
    _report(study, study["pilot"])
    _report(study, study["pilot"], "detailed")
    _report(study, study["hidden"])
    nav = _build(study)
    assert (nav.reports_enabled, nav.report_count) == (True, 1)
    assert len(login_as(study["patient"]).get("/api/reports/").get_json()) == 1


def test_reports_off_hides_the_count(study, db):
    _report(study, study["pilot"])
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, enable_nlp_report=False))
    db.session.commit()
    nav = _build(study)
    assert (nav.reports_enabled, nav.report_count) == (False, 0)


def test_opening_hours_off_by_default(study, login_as):
    assert _build(study).opening_hours == {"enabled": False}
    assert login_as(study["patient"]).get("/api/access-window").get_json() == {"enabled": False}


@pytest.mark.parametrize("is_open", [True, False])
def test_opening_hours_open_and_closed(study, db, login_as, monkeypatch, is_open):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, access_hours_enabled=True,
                                        access_hours_start="09:00", access_hours_end="17:00"))
    db.session.commit()
    from llm_chat.utils import access_hours
    monkeypatch.setattr(access_hours, "within_access_window", lambda *a, **k: is_open)
    hours = _build(study).opening_hours
    assert hours["enabled"] is True and hours["open"] is is_open
    assert ("9:00 AM" in hours["schedule"]) and ((hours["reopen"] is None) == is_open)
    assert login_as(study["patient"]).get("/api/access-window").get_json() == hours


def test_focus_group_is_the_one_with_work_in_progress(study, db):
    nav = _build(study)
    assert nav.focus_group().name == "Week 1"                          # Thought records, in progress
    assert nav.focus_group(study["star"].id).name == "Characters"      # the current exercise wins
    study["thoughts_conv"].window_id = None                            # nothing in progress
    study["thoughts_conv"].template_id = None
    db.session.commit()
    assert _build(study).focus_group().name == "Characters"            # first open group with work left
