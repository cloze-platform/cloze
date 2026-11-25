"""participant_nav.build: what a participant can see, shared by the new pages
and today's /api/windows/current and /api/conversations.

The snapshot test pins both APIs' responses for a seeded study. It was
recorded from the code before they moved onto participant_nav, so the
refactor can't change what today's dashboard shows. Re-record only for an
intended change:  CLOZE_UPDATE_SNAPSHOTS=1 pytest tests/test_participant_nav.py
"""

import json
import os
import time
from pathlib import Path

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import (AdminSettings, ChatTemplate, ChatWindow, Conversation, Message, Model,
                             ProviderFeatureFlags, ProviderPatient, Report, SafetyPlan, SavedSelection)

NOW = 1_800_000_000.0
DAY = 86_400.0
SNAPSHOT = Path(__file__).parent / "snapshots" / "participant_apis.json"


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    return NOW


@pytest.fixture
def study(app, frozen, make_user):
    """A participant with windows in every state, plus another participant's
    window that must never show up."""
    s = {}
    model = Model(name="test-model", provider="local", model_identifier="test")
    _db.session.add(model)
    _db.session.flush()
    provider = make_user("prov", role="provider")
    patient = make_user("pt")
    other = make_user("pt2")
    _db.session.add_all([ProviderPatient(provider_id=provider.id, patient_id=patient.id),
                         ProviderPatient(provider_id=provider.id, patient_id=other.id)])

    def window(title, start, end, user=patient, visible=True, status="scheduled", **kw):
        w = ChatWindow(patient_id=user.id, provider_id=provider.id, title=title,
                       description=f"About {title}", start_date=NOW + start, end_date=NOW + end,
                       visible=visible, status=status, created_at=NOW - 40 * DAY, **kw)
        _db.session.add(w)
        _db.session.flush()
        return w

    def template(w, title, order, visible=True):
        t = ChatTemplate(window_id=w.id, title=title, purpose=f"Purpose of {title}", model_id=model.id,
                         order_index=order, visible=visible, created_at=NOW - 40 * DAY)
        _db.session.add(t)
        _db.session.flush()
        return t

    def conversation(t=None, user=patient, messages=0, visible=True, updated=-DAY, title=None):
        c = Conversation(user_id=user.id, title=title or (t.title if t else "Free chat"), model_id=model.id,
                         window_id=t.window_id if t else None, template_id=t.id if t else None,
                         visible=visible, created_at=NOW + updated - 600, updated_at=NOW + updated)
        _db.session.add(c)
        _db.session.flush()
        for i in range(messages):
            _db.session.add(Message(conversation_id=c.id, role="user" if i % 2 == 0 else "assistant",
                                    content=f"message {i}", timestamp=NOW + updated - 500 + i))
        return c

    # Week 1: open now. One started, one not, one hidden template.
    s["week1"] = w1 = window("Week 1", -2 * DAY, 5 * DAY, flow_name="CBT", phase_label="Week 1")
    s["thoughts"] = t1 = template(w1, "Thought records", 0)
    s["checkin"] = template(w1, "Check-in", 1)
    template(w1, "Hidden chat", 2, visible=False)
    s["thoughts_conv"] = conversation(t1, messages=4, updated=-3600)
    # Week 2: opens in five days.
    s["week2"] = w2 = window("Week 2", 5 * DAY, 12 * DAY, flow_name="CBT", phase_label="Week 2")
    s["activation"] = template(w2, "Behavioural activation", 0)
    # Intro: ended three days ago, report not generated yet.
    s["intro"] = w3 = window("Intro", -10 * DAY, -3 * DAY, flow_name="CBT", phase_label="Intro")
    s["welcome_conv"] = conversation(template(w3, "Welcome", 0), messages=2, updated=-4 * DAY)
    template(w3, "Never started", 1)
    # Characters: always available; one conversation created but never sent to.
    s["characters"] = w5 = window("Characters", -30 * DAY, 300 * DAY, flow_name="Characters")
    s["sky"] = template(w5, "Sky", 0)
    s["star"] = star = template(w5, "Star", 1)
    s["star_conv"] = conversation(star, messages=0, updated=-2 * DAY)
    # Pilot: ended, report ready.
    s["pilot"] = w6 = window("Pilot", -60 * DAY, -50 * DAY, status="report_ready", flow_name="Pilot")
    s["pilot_conv"] = conversation(template(w6, "Pilot chat", 0), messages=2, updated=-50 * DAY)
    # A hidden window, open by date, with a conversation.
    s["hidden"] = w4 = window("Hidden window", -DAY, DAY, visible=False)
    conversation(template(w4, "Secret", 0), messages=2, updated=-600)
    # Conversations outside any window.
    conversation(messages=2, updated=-20 * DAY, title="Old free chat")
    conversation(messages=0, visible=False, updated=-21 * DAY, title="Empty hidden chat")
    conversation(messages=2, visible=False, updated=-22 * DAY, title="Hidden chat with messages")
    # Another participant's open window.
    w7 = window("Someone else's week", -DAY, DAY, user=other)
    conversation(template(w7, "Not yours", 0), user=other, messages=2)

    _db.session.commit()
    s.update(provider=provider, patient=patient, other=other, model=model)
    return s


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
