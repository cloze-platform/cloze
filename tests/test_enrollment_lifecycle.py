"""Enrollment lifecycle: withdrawal (issue #8) and chat-less always-available
flows with later backfill (issue #10).

The invariant running through all of it: withdrawing a participant must never
destroy data. Conversations, finished windows and the enrollment row itself
survive, because the report-v2 scope engine resolves reports through them.
"""
import time

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models.chat import Model
from llm_chat.models.chat_window import ChatWindow
from llm_chat.models.core import ProviderPatient
from llm_chat.models.study_flow import StudyFlow, FlowPhase, FlowChat, FlowEnrollment


DAY = 86400

# The app-wide CSRF guard (llm_chat/__init__.py) rejects state-changing /api/
# requests without a JSON content type, DELETE included.
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
    p = make_user("pt", role="user")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=p.id))
    _db.session.commit()
    return p


@pytest.fixture
def make_flow(provider):
    def _make(flow_type="always", with_phase=True, name="Flow A"):
        flow = StudyFlow(provider_id=provider.id, name=name, flow_type=flow_type)
        _db.session.add(flow)
        _db.session.flush()
        if with_phase:
            _db.session.add(FlowPhase(flow_id=flow.id, name="Phase 1", order_index=0))
        _db.session.commit()
        return flow
    return _make


def add_chat(phase, model, title="Chat 1"):
    chat = FlowChat(phase_id=phase.id, title=title, model_id=model.id, order_index=0)
    _db.session.add(chat)
    _db.session.commit()
    return chat


# ── Issue #10: enrolling into a chat-less always-available flow ──────────


def test_always_flow_accepts_enrollment_with_no_chats(app, login_as, provider, patient, make_flow):
    flow = make_flow(flow_type="always")
    c = login_as(provider)

    resp = c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert resp.status_code == 200
    assert resp.get_json()["enrolled"] == 1
    assert FlowEnrollment.query.filter_by(flow_id=flow.id, patient_id=patient.id).count() == 1


def test_always_flow_accepts_enrollment_with_no_phases_at_all(app, login_as, provider, patient, make_flow):
    flow = make_flow(flow_type="always", with_phase=False)
    c = login_as(provider)

    resp = c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert resp.status_code == 200
    assert ChatWindow.query.filter_by(patient_id=patient.id).count() == 0


@pytest.mark.parametrize("flow_type", ["phased", "recurring"])
def test_dated_flows_still_require_chats_before_enrolling(
    app, login_as, provider, patient, make_flow, flow_type
):
    """The guard is relaxed only for always-available flows."""
    flow = make_flow(flow_type=flow_type)
    c = login_as(provider)

    resp = c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert resp.status_code == 400
    assert "at least one phase with chats" in resp.get_json()["error"]


def test_chat_added_later_backfills_to_enrolled_participant(
    app, login_as, provider, patient, make_flow, model
):
    """Enroll first, design later — the whole point of relaxing the guard."""
    flow = make_flow(flow_type="always")
    phase = flow.phases[0]
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    resp = c.post(f"/api/provider/phases/{phase.id}/chats",
                  json={"title": "Check-in", "model_id": model.id})

    assert resp.status_code == 201
    assert resp.get_json()["backfilled_enrollments"] == 1

    window = ChatWindow.query.filter_by(patient_id=patient.id, flow_id=flow.id).one()
    titles = [t.title for t in window.templates.all()]
    assert titles == ["Check-in"]


def test_backfill_creates_the_window_when_the_phase_postdates_enrollment(
    app, login_as, provider, patient, make_flow, model
):
    """Enrolled before the phase existed, so there is no window to extend."""
    flow = make_flow(flow_type="always", with_phase=False)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    assert ChatWindow.query.filter_by(patient_id=patient.id).count() == 0

    resp = c.post(f"/api/provider/flows/{flow.id}/phases", json={"name": "Phase 1"})
    phase_id = resp.get_json()["id"]
    c.post(f"/api/provider/phases/{phase_id}/chats",
           json={"title": "Check-in", "model_id": model.id})

    window = ChatWindow.query.filter_by(patient_id=patient.id, flow_id=flow.id).one()
    assert window.phase_id == phase_id
    assert [t.title for t in window.templates.all()] == ["Check-in"]


def test_backfill_skips_withdrawn_participants(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    phase = flow.phases[0]
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    resp = c.post(f"/api/provider/phases/{phase.id}/chats",
                  json={"title": "Check-in", "model_id": model.id})

    assert resp.get_json()["backfilled_enrollments"] == 0


def test_backfill_does_not_touch_dated_flows(
    app, login_as, provider, patient, make_flow, model
):
    """Phased windows are pinned to dates and may already have closed."""
    flow = make_flow(flow_type="phased")
    phase = flow.phases[0]
    add_chat(phase, model, title="First")
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    resp = c.post(f"/api/provider/phases/{phase.id}/chats",
                  json={"title": "Second", "model_id": model.id})

    assert resp.get_json()["backfilled_enrollments"] == 0
    window = ChatWindow.query.filter_by(patient_id=patient.id, flow_id=flow.id).one()
    assert [t.title for t in window.templates.all()] == ["First"]


# ── Issue #8: withdrawal ─────────────────────────────────────────────────


def test_unenroll_soft_deletes_and_keeps_the_row(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    enrollment_id = FlowEnrollment.query.filter_by(flow_id=flow.id).one().id

    resp = c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    assert resp.status_code == 200
    enrollment = _db.session.get(FlowEnrollment, enrollment_id)
    assert enrollment is not None, "the row must survive — report scopes resolve through it"
    assert enrollment.status == FlowEnrollment.STATUS_WITHDRAWN
    assert enrollment.withdrawn_at is not None
    assert not enrollment.is_active


def test_unenroll_hides_unfinished_windows_but_keeps_finished_ones(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    # A window that already closed: the historical record.
    now = time.time()
    finished = ChatWindow(
        patient_id=patient.id, provider_id=provider.id, title="Done",
        start_date=now - (30 * DAY), end_date=now - DAY,
        flow_id=flow.id, flow_name=flow.name,
    )
    _db.session.add(finished)
    _db.session.commit()
    finished_id = finished.id

    resp = c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    assert resp.get_json()["windows_hidden"] == 1
    assert _db.session.get(ChatWindow, finished_id).visible is True
    open_window = ChatWindow.query.filter(
        ChatWindow.patient_id == patient.id, ChatWindow.id != finished_id
    ).one()
    assert open_window.visible is False


def test_unenroll_preserves_conversations(
    app, login_as, provider, patient, make_flow, model
):
    from llm_chat.models.chat import Conversation

    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    window = ChatWindow.query.filter_by(patient_id=patient.id).one()

    conv = Conversation(user_id=patient.id, model_id=model.id, window_id=window.id)
    _db.session.add(conv)
    _db.session.commit()
    conv_id = conv.id

    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    assert _db.session.get(Conversation, conv_id) is not None


def test_unenroll_is_404_when_not_enrolled(app, login_as, provider, patient, make_flow):
    flow = make_flow(flow_type="always")
    c = login_as(provider)

    assert c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS).status_code == 404


def test_unenroll_twice_is_404_the_second_time(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS).status_code == 200
    assert c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS).status_code == 404


def test_unenroll_rejects_another_providers_flow(
    app, login_as, make_user, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    login_as(provider).post(f"/api/provider/flows/{flow.id}/enroll",
                            json={"patient_ids": [patient.id]})

    intruder = make_user("other-prov", role="provider")
    resp = login_as(intruder).delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    assert resp.status_code == 403


def test_unenroll_matches_legacy_windows_by_flow_name(
    app, login_as, provider, patient, make_flow, model
):
    """Windows generated before the flow_id FK existed carry only flow_name."""
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    now = time.time()
    legacy = ChatWindow(
        patient_id=patient.id, provider_id=provider.id, title="Legacy",
        start_date=now - DAY, end_date=now + (30 * DAY),
        flow_id=None, flow_name=flow.name,
    )
    _db.session.add(legacy)
    _db.session.commit()
    legacy_id = legacy.id

    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    assert _db.session.get(ChatWindow, legacy_id).visible is False


# ── Legacy rows and re-enrollment ────────────────────────────────────────


def test_null_status_reads_as_active(app, provider, patient, make_flow):
    """Rows predating the column have status NULL and must count as enrolled."""
    flow = make_flow(flow_type="always")
    enrollment = FlowEnrollment(flow_id=flow.id, patient_id=patient.id,
                                enrolled_at=time.time(), status=None)
    _db.session.add(enrollment)
    _db.session.commit()

    assert enrollment.is_active
    assert enrollment.to_dict()["status"] == "active"
    matched = FlowEnrollment.query.filter(
        FlowEnrollment.flow_id == flow.id, FlowEnrollment.active_filter()
    ).all()
    assert [e.id for e in matched] == [enrollment.id]


def test_enrollment_count_excludes_withdrawn(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    assert flow.to_dict()["enrollment_count"] == 1

    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)
    _db.session.refresh(flow)

    assert flow.to_dict()["enrollment_count"] == 0


def test_reenrollment_reuses_the_enrollment_id(
    app, login_as, provider, patient, make_flow, model
):
    """Stable ids keep saved report-v2 'enrollment' scopes pointing at data."""
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    original_id = FlowEnrollment.query.filter_by(flow_id=flow.id).one().id

    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)
    resp = c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert resp.get_json()["enrolled"] == 1
    enrollment = FlowEnrollment.query.filter_by(flow_id=flow.id).one()
    assert enrollment.id == original_id
    assert enrollment.is_active
    assert enrollment.withdrawn_at is None


def test_enrolling_an_already_active_participant_is_a_no_op(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    resp = c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    assert resp.get_json()["enrolled"] == 0
    assert ChatWindow.query.filter_by(patient_id=patient.id).count() == 1


def test_get_enrollments_reports_withdrawn_status(
    app, login_as, provider, patient, make_flow, model
):
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    body = c.get(f"/api/provider/flows/{flow.id}/enrollments").get_json()

    assert len(body) == 1, "withdrawn participants stay listed so they can be re-enrolled"
    assert body[0]["status"] == "withdrawn"


def test_withdrawn_participant_sees_nothing_but_history_survives(
    app, login_as, provider, patient, make_flow, model
):
    """End-to-end: the participant's view empties out, the data does not."""
    from llm_chat.models.chat import Conversation, Message

    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model, title="Check-in")
    prov = login_as(provider)
    prov.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})

    window = ChatWindow.query.filter_by(patient_id=patient.id).one()
    conv = Conversation(user_id=patient.id, model_id=model.id, window_id=window.id)
    _db.session.add(conv)
    _db.session.flush()
    _db.session.add(Message(conversation_id=conv.id, role="user", content="hello",
                            timestamp=time.time()))
    _db.session.commit()
    conv_id = conv.id

    assert login_as(patient).get("/api/conversations").get_json(), "precondition: sees the flow"

    # login_as re-seeds the Flask-Login identity cached on `g`; without this the
    # request below would still resolve as the patient and 403.
    resp = login_as(provider).delete(
        f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)
    assert resp.status_code == 200

    assert login_as(patient).get("/api/conversations").get_json() == []
    surviving = _db.session.get(Conversation, conv_id)
    assert surviving is not None
    assert surviving.messages.count() == 1


def test_flow_with_withdrawn_participants_cannot_be_deleted(
    app, login_as, provider, patient, make_flow, model
):
    """Their windows still FK to the flow and their reports resolve through it."""
    flow = make_flow(flow_type="always")
    add_chat(flow.phases[0], model)
    c = login_as(provider)
    c.post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    c.delete(f"/api/provider/flows/{flow.id}/enroll/{patient.id}", headers=JSON_HEADERS)

    resp = c.delete(f"/api/provider/flows/{flow.id}", headers=JSON_HEADERS)

    assert resp.status_code == 400
    assert "withdrawn participants" in resp.get_json()["error"]
    assert _db.session.get(StudyFlow, flow.id) is not None
