"""Stage 2 groups: a study flow's phases as researcher-made groups.

A group is a phase underneath: always-available flows can now have several,
each with a line for its card, in an order the research team sets.
"""

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import Model, ProviderPatient
from llm_chat.models.study_flow import FlowChat, FlowPhase, StudyFlow



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
