"""Participants' chats remember the study-design chat they came from
(ChatTemplate.flow_chat_id), so settings read through that link reach
participants already enrolled."""
import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import ChatTemplate, ChatWindow, FlowChat, FlowPhase, Model, ProviderPatient, StudyFlow
from llm_chat.services.flow_links import link_templates_to_flow_chats

JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def model(app):
    m = Model(name="test-model", provider="local", model_identifier="test")
    _db.session.add(m)
    _db.session.commit()
    return m


@pytest.fixture
def provider(make_user):
    return make_user("prov", role="provider")


@pytest.fixture
def patient(make_user, provider):
    p = make_user("pt")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=p.id))
    _db.session.commit()
    return p


@pytest.fixture
def flow(provider, model):
    """An always-available flow with two chats."""
    f = StudyFlow(provider_id=provider.id, name="Characters", flow_type="always")
    _db.session.add(f)
    _db.session.flush()
    phase = FlowPhase(flow_id=f.id, name="Phase 1", order_index=0)
    _db.session.add(phase)
    _db.session.flush()
    _db.session.add_all([FlowChat(phase_id=phase.id, title="Ann", model_id=model.id, order_index=0),
                         FlowChat(phase_id=phase.id, title="Alex", model_id=model.id, order_index=1)])
    _db.session.commit()
    return f


def enroll(login_as, provider, patient, flow):
    resp = login_as(provider).post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    assert resp.status_code == 200, resp.get_json()


def chat_id(title):
    return FlowChat.query.filter_by(title=title).one().id


def test_enrollment_links_each_chat_to_its_study_design_chat(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    templates = ChatTemplate.query.all()
    assert len(templates) == 2
    for template in templates:
        assert template.flow_chat_id == chat_id(template.title)


def test_chats_added_later_are_linked_too(login_as, provider, patient, flow, model):
    enroll(login_as, provider, patient, flow)
    resp = login_as(provider).post(f"/api/provider/phases/{FlowPhase.query.one().id}/chats",
                                   json={"title": "Sam", "model_id": model.id})
    assert resp.status_code == 201
    assert ChatTemplate.query.filter_by(title="Sam").one().flow_chat_id == resp.get_json()["id"]


def test_deleting_a_study_chat_unlinks_participant_chats(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    ann = chat_id("Ann")
    assert login_as(provider).delete(f"/api/provider/chats/{ann}", headers=JSON_HEADERS).status_code == 200
    assert ChatTemplate.query.filter_by(title="Ann").one().flow_chat_id is None
    assert ChatTemplate.query.filter_by(title="Alex").one().flow_chat_id == chat_id("Alex")


def test_deleting_a_phase_unlinks_participant_chats(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    phase = FlowPhase.query.one()
    assert login_as(provider).delete(f"/api/provider/phases/{phase.id}", headers=JSON_HEADERS).status_code == 200
    assert [t.flow_chat_id for t in ChatTemplate.query.all()] == [None, None]


def test_backfill_links_only_unambiguous_matches(provider, patient, flow, model):
    phase = FlowPhase.query.one()
    # A second "Alex" in the phase makes Alex ambiguous.
    _db.session.add(FlowChat(phase_id=phase.id, title="Alex", model_id=model.id, order_index=2))
    window = ChatWindow(patient_id=patient.id, provider_id=provider.id, title="Phase 1",
                        start_date=0, end_date=4102444800, flow_id=flow.id, phase_id=phase.id)
    _db.session.add(window)
    _db.session.flush()
    for title in ("Ann", "Alex", "Something else"):
        _db.session.add(ChatTemplate(window_id=window.id, title=title, model_id=model.id))
    _db.session.commit()

    assert link_templates_to_flow_chats() == 1
    links = {t.title: t.flow_chat_id for t in ChatTemplate.query.all()}
    assert links == {"Ann": chat_id("Ann"), "Alex": None, "Something else": None}
    assert link_templates_to_flow_chats() == 0  # idempotent
