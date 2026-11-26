"""Why a conversation ended: Conversation.ended_at and end_reason."""

import pytest

from conftest import NOW
from llm_chat.models import Conversation, ProviderFeatureFlags, SafetyPlan
from llm_chat.services import participant_nav
from llm_chat.services.conversation_end import backfill_window_closed, end, stamp_window_closed
from llm_chat.services.llm_interface import LLMInterface


@pytest.fixture
def replies(monkeypatch):
    """The AI call, answered locally. Records the history it was sent."""
    calls = []

    def fake(model, history, system_prompt=None, *args, **kwargs):
        calls.append(history)
        return f"reply {len(calls)}", 0.01
    monkeypatch.setattr(LLMInterface, "call_llm", staticmethod(fake))
    return calls


def _limit(db, study, turns):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=turns))
    db.session.commit()


def _send(client, conversation, text="hello"):
    return client.post(f"/api/conversation/{conversation.id}/message", json={"message": text})


# ── Recording an end ──

def test_end_records_once_and_keeps_updated_at(study, db):
    conv = study["thoughts_conv"]
    before = conv.updated_at
    assert end(conv, Conversation.TURN_LIMIT, at=NOW - 5) is True
    db.session.commit()
    db.session.expire_all()
    conv = db.session.get(Conversation, conv.id)
    assert (conv.ended_at, conv.end_reason, conv.updated_at) == (NOW - 5, "turn_limit", before)
    assert end(conv, Conversation.WINDOW_CLOSED) is False            # already ended: unchanged
    assert conv.end_reason == "turn_limit"


def test_window_closed_is_stamped_at_the_windows_end(study, db):
    conv, window = study["welcome_conv"], study["intro"]
    assert stamp_window_closed(conv, window) is True
    db.session.commit()
    assert (conv.ended_at, conv.end_reason) == (window.end_date, "window_closed")


def test_open_and_upcoming_windows_are_not_stamped(study):
    assert stamp_window_closed(study["thoughts_conv"], study["week1"]) is False
    assert study["thoughts_conv"].ended_at is None


def test_a_report_ready_window_ends_its_conversations_no_later_than_now(study, db):
    study["week1"].status = "report_ready"           # closed early by its report
    db.session.commit()
    assert stamp_window_closed(study["thoughts_conv"], study["week1"]) is True
    assert study["thoughts_conv"].ended_at == NOW


def test_backfill_marks_only_conversations_in_ended_windows(study, db):
    updated = {c.id: c.updated_at for c in Conversation.query.all()}
    assert backfill_window_closed() == 2                               # Welcome, Pilot chat
    db.session.expire_all()
    ended = {c.title: c.end_reason for c in Conversation.query.filter(Conversation.ended_at.isnot(None))}
    assert ended == {"Welcome": "window_closed", "Pilot chat": "window_closed"}
    assert {c.id: c.updated_at for c in Conversation.query.all()} == updated
    assert backfill_window_closed() == 0                               # idempotent


def test_reading_the_menu_records_closed_windows(study, db):
    nav = participant_nav.build(study["patient"])
    db.session.expire_all()
    welcome = db.session.get(Conversation, study["welcome_conv"].id)
    assert welcome.end_reason == "window_closed"
    assert nav.exercise_for_conversation(welcome.id).state == "finished"


def test_the_list_apis_are_unchanged_by_stamping(study, login_as):
    """Stamping happens inside /api/conversations, and mustn't reorder it."""
    client = login_as(study["patient"])
    first = client.get("/api/conversations").get_json()
    assert client.get("/api/conversations").get_json() == first


# ── Sending ──

def test_the_last_turn_ends_the_conversation(study, db, login_as, replies):
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="active"))
    _limit(db, study, 3)                        # Thought records has used 2
    client = login_as(study["patient"])
    resp = _send(client, study["thoughts_conv"])
    assert resp.status_code == 200 and resp.get_json()["turn_limit_reached"] is True
    conv = db.session.get(Conversation, study["thoughts_conv"].id)
    assert (conv.end_reason, conv.ended_at) == ("turn_limit", NOW)

    again = _send(client, study["thoughts_conv"])
    assert again.status_code == 403
    assert again.get_json() == {"error": "This conversation has used all its turns.", "ended": True,
                                "end_reason": "turn_limit", "turn_limit_reached": True, "max_turns": 3}
    assert len(replies) == 1


def test_raising_the_limit_does_not_reopen_an_ended_conversation(study, db, login_as, replies):
    _limit(db, study, 3)
    _send(login_as(study["patient"]), study["thoughts_conv"])
    ProviderFeatureFlags.query.first().max_turns_per_conversation = 10
    db.session.commit()
    assert _send(login_as(study["patient"]), study["thoughts_conv"]).status_code == 403


def test_a_turn_before_the_last_does_not_end_it(study, db, login_as, replies):
    _limit(db, study, 5)
    assert _send(login_as(study["patient"]), study["thoughts_conv"]).status_code == 200
    assert db.session.get(Conversation, study["thoughts_conv"].id).ended_at is None


def test_sending_after_the_window_closes_is_refused_with_the_reason(study, db, login_as, replies):
    resp = _send(login_as(study["patient"]), study["welcome_conv"])
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "This chat window has closed.", "ended": True, "end_reason": "window_closed"}
    assert db.session.get(Conversation, study["welcome_conv"].id).end_reason == "window_closed"
    assert replies == []


def test_upcoming_windows_keep_their_refusal(study, db, login_as, replies):
    conv = Conversation(user_id=study["patient"].id, model_id=study["model"].id, title="Early",
                        window_id=study["week2"].id, template_id=study["activation"].id)
    db.session.add(conv)
    db.session.commit()
    resp = _send(login_as(study["patient"]), conv)
    assert resp.status_code == 403 and "expired or is no longer active" in resp.get_json()["error"]
    assert conv.ended_at is None


# ── Reading ──

def test_conversation_api_returns_and_records_the_reason(study, db, login_as):
    data = login_as(study["patient"]).get(f"/api/conversation/{study['pilot_conv'].id}").get_json()
    assert data["end_reason"] == "window_closed" and data["ended_at"] == study["pilot"].end_date
    open_conv = login_as(study["patient"]).get(f"/api/conversation/{study['thoughts_conv'].id}").get_json()
    assert open_conv["ended_at"] is None and open_conv["end_reason"] is None


def test_a_recorded_turn_limit_shows_on_todays_page(study, db, login_as):
    _limit(db, study, 10)
    end(study["thoughts_conv"], Conversation.TURN_LIMIT)
    db.session.commit()
    data = login_as(study["patient"]).get(f"/api/conversation/{study['thoughts_conv'].id}").get_json()
    assert data["turn_limit_reached"] is True and data["turns_remaining"] == 8
