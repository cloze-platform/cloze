"""Stage 2 groups: a study flow's phases as researcher-made groups.

A group is a phase underneath. The participant's menu and Home read the phase
as it is now, so renames, card lines and reordering reach people already
enrolled. An always-available flow with one group still shows under the
flow's name, as before; with several, each group shows its own name.
"""

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import ChatWindow, Model, ProviderPatient
from llm_chat.models.study_flow import FlowChat, FlowEnrollment, FlowPhase, StudyFlow
from llm_chat.services import participant_nav

from conftest import DAY, NOW


@pytest.fixture
def setup(app, frozen, make_user):
    model = Model(name="test-model", provider="local", model_identifier="test")
    _db.session.add(model)
    provider = make_user("prov", role="provider")
    other_provider = make_user("prov2", role="provider")
    patient = make_user("pt")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=patient.id))
    _db.session.commit()
    return {"model": model, "provider": provider, "other_provider": other_provider, "patient": patient}


def make_flow(setup, flow_type="always", name="Practice", phases=(FlowPhase.DEFAULT_ALWAYS_NAME,)):
    flow = StudyFlow(provider_id=setup["provider"].id, name=name, flow_type=flow_type,
                     cadence_days=7 if flow_type == "recurring" else None,
                     cycle_count=2 if flow_type == "recurring" else None)
    _db.session.add(flow)
    _db.session.flush()
    for i, phase_name in enumerate(phases):
        _db.session.add(FlowPhase(flow_id=flow.id, name=phase_name, order_index=i,
                                  start_day=i * 7 if flow_type == "phased" else 0,
                                  end_day=(i + 1) * 7 if flow_type == "phased" else None))
    _db.session.commit()
    return flow


def add_chat(setup, phase, title):
    chat = FlowChat(phase_id=phase.id, title=title, model_id=setup["model"].id, order_index=0)
    _db.session.add(chat)
    _db.session.commit()
    return chat


def enroll(client, flow, patient):
    resp = client.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    assert resp.status_code == 200, resp.get_json()


def menu(setup):
    return [(g.name, g.blurb) for g in participant_nav.build(setup["patient"]).menu_groups if g.exercises]


# ── The researcher's API ───────────────────────────────────────

def test_adding_a_second_group_names_the_first_after_the_flow(setup, login_as):
    flow = make_flow(setup)
    c = login_as(setup["provider"])

    resp = c.post(f"/api/provider/flows/{flow.id}/phases",
                  json={"name": " Character practice ", "description": "Short chats with Sky and Star"})

    assert resp.status_code == 201
    new = resp.get_json()
    assert (new["name"], new["description"], new["order_index"]) == ("Character practice", "Short chats with Sky and Star", 1)
    assert (new["start_day"], new["end_day"]) == (0, None)
    # Participants knew the single group by the flow's name, so that's its name now.
    assert [p.name for p in StudyFlow.query.get(flow.id).phases] == ["Practice", "Character practice"]


def test_a_first_group_the_team_named_keeps_its_name(setup, login_as):
    flow = make_flow(setup, phases=("Warm-up",))
    login_as(setup["provider"]).post(f"/api/provider/flows/{flow.id}/phases", json={"name": "Practice"})
    assert [p.name for p in StudyFlow.query.get(flow.id).phases] == ["Warm-up", "Practice"]


def test_recurring_flows_keep_one_group(setup, login_as):
    flow = make_flow(setup, flow_type="recurring", phases=("Each Cycle",))
    resp = login_as(setup["provider"]).post(f"/api/provider/flows/{flow.id}/phases", json={"name": "More"})
    assert resp.status_code == 400
    assert len(StudyFlow.query.get(flow.id).phases) == 1


@pytest.mark.parametrize("body", [
    {"name": "   "},
    {"name": 42},
    {"name": "x" * (FlowPhase.NAME_LIMIT + 1)},
    {"name": "Fine", "description": "y" * (FlowPhase.DESCRIPTION_LIMIT + 1)},
    {"name": "Fine", "description": ["not", "text"]},
])
def test_group_names_and_lines_are_checked(setup, login_as, body):
    flow = make_flow(setup)
    resp = login_as(setup["provider"]).post(f"/api/provider/flows/{flow.id}/phases", json=body)
    assert resp.status_code == 400
    assert len(StudyFlow.query.get(flow.id).phases) == 1


def test_editing_and_clearing_a_groups_line(setup, login_as):
    flow = make_flow(setup, phases=("A", "B"))
    phase = flow.phases[1]
    c = login_as(setup["provider"])

    assert c.put(f"/api/provider/phases/{phase.id}", json={"description": "  Two minutes each  "}).get_json()["description"] == "Two minutes each"
    assert c.put(f"/api/provider/phases/{phase.id}", json={"description": ""}).get_json()["description"] is None
    assert c.put(f"/api/provider/phases/{phase.id}", json={"name": ""}).status_code == 400
    assert _db.session.get(FlowPhase, phase.id).name == "B"


def test_reordering_groups(setup, login_as):
    flow = make_flow(setup, phases=("A", "B", "C"))
    a, b, c_ = (p.id for p in flow.phases)

    resp = login_as(setup["provider"]).put(f"/api/provider/flows/{flow.id}/phase-order", json={"phase_ids": [c_, a, b]})

    assert resp.status_code == 200
    assert [p["name"] for p in resp.get_json()["phases"]] == ["C", "A", "B"]


@pytest.mark.parametrize("make_ids", [
    lambda a, b, c, other: [a, b],            # one missing
    lambda a, b, c, other: [a, b, c, c],      # one twice
    lambda a, b, c, other: [a, b, other],     # another flow's group
    lambda a, b, c, other: [a, b, True],      # not an id
    lambda a, b, c, other: "a,b,c",           # not a list
])
def test_reordering_needs_every_group_once(setup, login_as, make_ids):
    flow = make_flow(setup, phases=("A", "B", "C"))
    other = make_flow(setup, name="Other", phases=("X",))
    ids = make_ids(*(p.id for p in flow.phases), other.phases[0].id)

    resp = login_as(setup["provider"]).put(f"/api/provider/flows/{flow.id}/phase-order", json={"phase_ids": ids})

    assert resp.status_code == 400
    assert [p.name for p in StudyFlow.query.get(flow.id).phases] == ["A", "B", "C"]


def test_another_researchers_groups_are_off_limits(setup, login_as):
    flow = make_flow(setup, phases=("A", "B"))
    c = login_as(setup["other_provider"])
    assert c.post(f"/api/provider/flows/{flow.id}/phases", json={"name": "Mine"}).status_code == 403
    assert c.put(f"/api/provider/phases/{flow.phases[0].id}", json={"description": "Mine"}).status_code == 403
    ids = [p.id for p in flow.phases][::-1]
    assert c.put(f"/api/provider/flows/{flow.id}/phase-order", json={"phase_ids": ids}).status_code == 403
    assert [p.name for p in StudyFlow.query.get(flow.id).phases] == ["A", "B"]


# ── What the participant sees ─────────────────────────────────

def test_one_group_shows_under_the_flows_name(setup, login_as):
    flow = make_flow(setup)
    add_chat(setup, flow.phases[0], "Sky")
    enroll(login_as(setup["provider"]), flow, setup["patient"])

    assert menu(setup) == [("Practice", None)]


def test_several_groups_show_their_names_and_lines_in_the_teams_order(setup, login_as):
    flow = make_flow(setup, phases=("Warm-up", "Characters"))
    warm, chars = flow.phases
    warm.description = "Start here"
    add_chat(setup, warm, "Breathing")
    add_chat(setup, chars, "Sky")
    c = login_as(setup["provider"])
    enroll(c, flow, setup["patient"])
    assert menu(setup) == [("Warm-up", "Start here"), ("Characters", None)]

    # Renames, lines and the order reach the participant already enrolled.
    c.put(f"/api/provider/phases/{chars.id}", json={"name": "Sky and Star", "description": "Practice chats"})
    c.put(f"/api/provider/flows/{flow.id}/phase-order", json={"phase_ids": [chars.id, warm.id]})
    _db.session.expire_all()
    assert menu(setup) == [("Sky and Star", "Practice chats"), ("Warm-up", "Start here")]


def test_a_group_added_after_enrolling_reaches_the_participant(setup, login_as):
    flow = make_flow(setup)
    add_chat(setup, flow.phases[0], "Breathing")
    c = login_as(setup["provider"])
    enroll(c, flow, setup["patient"])

    phase_id = c.post(f"/api/provider/flows/{flow.id}/phases", json={"name": "Characters"}).get_json()["id"]
    resp = c.post(f"/api/provider/phases/{phase_id}/chats", json={"title": "Sky", "model_id": setup["model"].id})
    assert resp.status_code == 201

    _db.session.expire_all()
    assert menu(setup) == [("Practice", None), ("Characters", None)]
    exercises = [e.title for g in participant_nav.build(setup["patient"]).menu_groups for e in g.exercises]
    assert exercises == ["Breathing", "Sky"]


def test_flows_follow_the_order_they_were_joined_then_hand_made_windows(setup, login_as):
    first = make_flow(setup, name="Second flow, joined first")
    second = make_flow(setup, name="First flow, joined second")
    add_chat(setup, first.phases[0], "A")
    add_chat(setup, second.phases[0], "B")
    c = login_as(setup["provider"])
    enroll(c, second, setup["patient"])
    enroll(c, first, setup["patient"])
    FlowEnrollment.query.filter_by(flow_id=first.id).one().enrolled_at = NOW - 10 * DAY
    FlowEnrollment.query.filter_by(flow_id=second.id).one().enrolled_at = NOW - 5 * DAY
    # A window made by hand, open since before either flow.
    from llm_chat.models import ChatTemplate
    handmade = ChatWindow(patient_id=setup["patient"].id, provider_id=setup["provider"].id, title="Extra",
                          start_date=NOW - 20 * DAY, end_date=NOW + 20 * DAY)
    _db.session.add(handmade)
    _db.session.flush()
    _db.session.add(ChatTemplate(window_id=handmade.id, title="Extra chat", model_id=setup["model"].id, order_index=0))
    _db.session.commit()

    assert [name for name, _ in menu(setup)] == ["Second flow, joined first", "First flow, joined second", "Extra"]


def test_recurring_cycles_keep_their_labels_in_date_order(setup, login_as):
    flow = make_flow(setup, flow_type="recurring", name="Check-ins", phases=("Each Cycle",))
    add_chat(setup, flow.phases[0], "Weekly check-in")
    enroll(login_as(setup["provider"]), flow, setup["patient"])

    groups = participant_nav.build(setup["patient"]).menu_groups
    assert [g.name for g in groups] == ["Cycle 1 of 2", "Cycle 2 of 2"]
    assert all(g.blurb is None for g in groups)


def test_a_phased_flows_groups_use_live_phase_names(setup, login_as):
    flow = make_flow(setup, flow_type="phased", name="Course", phases=("Week 1", "Week 2"))
    w1, w2 = flow.phases
    add_chat(setup, w1, "Intro")
    add_chat(setup, w2, "Practice")
    c = login_as(setup["provider"])
    enroll(c, flow, setup["patient"])
    c.put(f"/api/provider/phases/{w2.id}", json={"name": "Week 2: practice"})
    _db.session.expire_all()

    assert [g.name for g in participant_nav.build(setup["patient"]).menu_groups] == ["Week 1", "Week 2: practice"]


def test_home_shows_the_groups_line_escaped(setup, login_as, v2):
    flow = make_flow(setup, phases=("Warm-up", "Characters"))
    flow.phases[0].description = "Start <b>here</b>"
    add_chat(setup, flow.phases[0], "Breathing")
    add_chat(setup, flow.phases[1], "Sky")
    enroll(login_as(setup["provider"]), flow, setup["patient"])

    page = login_as(setup["patient"]).get("/dashboard").get_data(as_text=True)

    assert "Start &lt;b&gt;here&lt;/b&gt;" in page
    assert page.index("Warm-up") < page.index("Characters")
