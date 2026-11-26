"""Saved selections feed a chat window's report, which the provider and the
participant read, so a user may only save one against a conversation they can
see."""
import pytest

from llm_chat.extensions import db as _db
from llm_chat.models.chat import Conversation, Model, SavedSelection
from llm_chat.models.core import ProviderPatient

JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def setup(make_user):
    provider = make_user("prov", role="provider")
    alice = make_user("alice", role="user")
    bob = make_user("bob", role="user")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=alice.id))
    model = Model(name="test-model", provider="local", model_identifier="test")
    _db.session.add(model)
    _db.session.flush()
    alice_conv = Conversation(user_id=alice.id, model_id=model.id, title="Alice")
    _db.session.add(alice_conv)
    _db.session.commit()
    return provider, alice, bob, alice_conv


def _save(client, conversation_id):
    return client.post("/api/save_selection", headers=JSON_HEADERS,
                       json={"conversation_id": conversation_id, "text": "quoted", "note": "n"})


def test_participant_saves_selection_on_own_conversation(login_as, setup):
    _, alice, _, conv = setup
    assert _save(login_as(alice), conv.id).status_code == 200
    assert SavedSelection.query.filter_by(conversation_id=conv.id).count() == 1


def test_participant_cannot_save_selection_on_someone_elses_conversation(login_as, setup):
    _, _, bob, conv = setup
    assert _save(login_as(bob), conv.id).status_code == 403
    assert SavedSelection.query.filter_by(conversation_id=conv.id).count() == 0


def test_provider_saves_selection_on_their_participants_conversation(login_as, setup):
    provider, _, _, conv = setup
    assert _save(login_as(provider), str(conv.id)).status_code == 200  # string ids still work


@pytest.mark.parametrize("bad_id", [None, "abc"])
def test_missing_or_malformed_conversation_id_is_rejected(login_as, setup, bad_id):
    _, alice, _, _ = setup
    assert _save(login_as(alice), bad_id).status_code == 400


def test_unknown_conversation_is_404(login_as, setup):
    _, alice, _, _ = setup
    assert _save(login_as(alice), 999999).status_code == 404


@pytest.mark.parametrize("body, status", [
    ({"text": "x" * 20_001}, 400),
    ({"text": "   "}, 400),
    ({"text": "ok", "note": "n" * 1001}, 400),
    ({"text": "ok", "message_ids": "1,2"}, 400),
    ({"text": "ok", "message_ids": ["1", 2]}, 200),         # today's pages send strings
])
def test_saved_selections_are_checked(login_as, setup, body, status):
    _, alice, _, conv = setup
    resp = login_as(alice).post("/api/save_selection", headers=JSON_HEADERS, json={"conversation_id": conv.id, **body})
    assert resp.status_code == status


def test_a_link_with_a_non_ascii_digit_just_opens_home(make_user, login_as, db):
    from llm_chat.models import AdminSettings
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()
    assert login_as(make_user("p")).get("/dashboard?conversation=²").status_code == 200
