"""Study-design chats must always keep a model.

The Study Design page only lists models that are available right now, so a
chat whose model is unavailable used to save with model_id null and fail with
a 500 (FlowChat.model_id is NOT NULL)."""
import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import FlowChat, FlowPhase, Model, StudyFlow


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
def phase(provider):
    flow = StudyFlow(provider_id=provider.id, name="Flow", flow_type="always")
    _db.session.add(flow)
    _db.session.flush()
    p = FlowPhase(flow_id=flow.id, name="Phase 1", order_index=0)
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture
def chat(phase, model):
    c = FlowChat(phase_id=phase.id, title="Ann", model_id=model.id, order_index=0)
    _db.session.add(c)
    _db.session.commit()
    return c


@pytest.mark.parametrize("bad", [None, "", "abc", 999999, True])
def test_saving_a_chat_without_a_real_model_is_refused(login_as, provider, chat, model, bad):
    resp = login_as(provider).put(f"/api/provider/chats/{chat.id}", json={"title": "Ann 2", "model_id": bad})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Choose a model for this chat."
    _db.session.expire_all()
    saved = _db.session.get(FlowChat, chat.id)
    assert (saved.title, saved.model_id) == ("Ann", model.id)


def test_saving_other_fields_keeps_the_model(login_as, provider, chat, model):
    # What the page sends when the chat's model isn't in the dropdown: no model_id.
    resp = login_as(provider).put(f"/api/provider/chats/{chat.id}", json={"title": "Ann 2"})
    assert resp.status_code == 200
    assert resp.get_json()["model_id"] == model.id
    assert resp.get_json()["title"] == "Ann 2"


def test_changing_the_model_still_works(login_as, provider, chat):
    other = Model(name="other-model", provider="local", model_identifier="other")
    _db.session.add(other)
    _db.session.commit()
    resp = login_as(provider).put(f"/api/provider/chats/{chat.id}", json={"model_id": str(other.id)})
    assert resp.status_code == 200
    assert resp.get_json()["model_id"] == other.id


@pytest.mark.parametrize("payload", [{}, {"model_id": None}, {"model_id": 999999}])
def test_adding_a_chat_without_a_real_model_is_refused(login_as, provider, phase, payload):
    resp = login_as(provider).post(f"/api/provider/phases/{phase.id}/chats", json={"title": "New", **payload})
    assert resp.status_code == 400
    assert FlowChat.query.count() == 0
