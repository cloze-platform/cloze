"""Sending that can't lose or duplicate a message (the new participant page).

The page sends a client_message_id with each message. The message is saved
before the model is called; a failed reply returns 502 and Try again completes
that message; a repeat of a finished one returns the saved reply. Without an
id (today's page), nothing changes.
"""

import json

import pytest
from sqlalchemy.exc import IntegrityError

from llm_chat.models import Conversation, EscalationEvent, Message, ProviderFeatureFlags
from llm_chat.services.llm_interface import LLMCallError, LLMInterface

ID = "0b6f1c2e-5a1d-4c55-9a43-7a1e1f0c9d21"


@pytest.fixture
def ai(monkeypatch):
    """The model: answers by default; set ai.fail = True to make every call fail
    the way a real provider error does (inside call_llm's own handling)."""
    class AI:
        fail = False
        block = False
        calls = 0
        histories = []

    real = LLMInterface.call_llm.__func__

    def call(cls, model, history, system_prompt=None, config_override=None, raise_on_error=False):
        AI.calls += 1
        AI.histories.append(history)
        if AI.block and raise_on_error:
            raise LLMCallError("I wasn't able to generate a response to that.", retryable=False)
        if AI.fail:
            monkeypatch.setattr(LLMInterface, "_provider_clients", {})
            model.provider, model.api_endpoint = "openai", None
            return real(cls, model, history, system_prompt, config_override, raise_on_error)
        return f"reply {AI.calls}", 0.01

    monkeypatch.setattr(LLMInterface, "call_llm", classmethod(call))
    monkeypatch.setattr(LLMInterface, "_dump_error_debug", classmethod(lambda *a, **k: None))
    return AI


def _send(client, conv, text="hello", client_id=ID):
    body = {"message": text}
    if client_id:
        body["client_message_id"] = client_id
    return client.post(f"/api/conversation/{conv.id}/message", json=body)


def _count(conv):
    return Message.query.filter_by(conversation_id=conv.id).count()


def test_a_failed_reply_keeps_the_message_and_says_so(study, login_as, ai, db):
    ai.fail = True
    conv = study["thoughts_conv"]
    before, title = _count(conv), conv.title
    resp = _send(login_as(study["patient"]), conv, "Something I needed to say")
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["reply_failed"] is True and body["retry"] is True and body["saved"] is True
    db.session.expire_all()
    kept = db.session.get(Message, body["user_message_id"])
    assert (kept.content, kept.client_message_id) == ("Something I needed to say", ID)
    assert _count(conv) == before + 1 and db.session.get(Conversation, conv.id).title == title


def test_try_again_completes_the_saved_message_without_using_another_turn(study, login_as, ai, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=4))
    db.session.commit()
    conv, client = study["thoughts_conv"], login_as(study["patient"])          # 2 turns used
    ai.fail = True
    assert _send(client, conv).status_code == 502
    ai.fail = False
    body = _send(client, conv).get_json()
    assert body["turns_remaining"] == 1 and ai.histories[-1][-1]["content"] == "hello"
    assert [m["content"] for m in ai.histories[-1]].count("hello") == 1


def test_a_blocked_reply_points_to_crisis_help(study, login_as, ai):
    ai.block = True
    resp = _send(login_as(study["patient"]), study["thoughts_conv"], "something the filter blocks")
    assert resp.status_code == 200
    assert "988" in resp.get_json()["response"] and "Get help now" in resp.get_json()["response"]


def test_a_message_left_without_a_reply_is_joined_to_the_next(study, login_as, ai):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    ai.fail = True
    _send(client, conv, "first thought", "first-message-id")
    ai.fail = False
    _send(client, conv, "second thought", "second-message-id")
    assert ai.histories[-1][-1] == {"role": "user", "content": "first thought\n\nsecond thought"}


def test_too_long_is_refused(study, login_as, ai):
    resp = _send(login_as(study["patient"]), study["thoughts_conv"], "x" * 10_001)
    assert resp.status_code == 400 and ai.calls == 0


def test_two_sends_of_one_message_at_once(study, login_as, ai, db, monkeypatch):
    """The other request saved the message first: this one is told it's in progress."""
    from llm_chat.services import guard
    conv = study["thoughts_conv"]

    def other_request_saves_it(*args, **kwargs):
        db.session.add(Message(conversation_id=conv.id, role="user", content="hello", timestamp=1,
                               client_message_id=ID))
        db.session.commit()
    monkeypatch.setattr(guard, "scan_and_escalate", other_request_saves_it)
    resp = _send(login_as(study["patient"]), conv)
    assert resp.status_code == 409 and resp.get_json()["in_progress"] is True and ai.calls == 0


def test_todays_page_still_gets_the_failure_as_a_reply(study, login_as, ai):
    ai.fail = True
    resp = _send(login_as(study["patient"]), study["thoughts_conv"], client_id=None)
    assert resp.status_code == 200 and resp.get_json()["response"].startswith("Something went wrong")


def test_try_again_after_a_failure_sends_once(study, login_as, ai):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    before = _count(conv)
    ai.fail = True
    assert _send(client, conv).status_code == 502
    ai.fail = False
    resp = _send(client, conv)
    assert resp.status_code == 200 and "repeat" not in resp.get_json()
    assert _count(conv) == before + 2
    assert Message.query.filter_by(conversation_id=conv.id, client_message_id=ID).count() == 1


def test_a_repeat_returns_the_saved_reply_without_asking_the_model_again(study, login_as, ai):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    first = _send(client, conv).get_json()
    again = _send(client, conv)
    assert again.status_code == 200
    body = again.get_json()
    assert body["repeat"] is True and body["message_id"] == first["message_id"]
    assert body["response"] == first["response"] and body["user_message_id"] == first["user_message_id"]
    assert ai.calls == 1


def test_a_repeat_of_the_last_turn_returns_its_reply_not_a_refusal(study, login_as, ai, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=3))
    db.session.commit()
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    first = _send(client, conv).get_json()
    assert first["ended"] is True and first["end_reason"] == "turn_limit"
    again = _send(client, conv)
    assert again.status_code == 200 and again.get_json()["turn_limit_reached"] is True
    assert _send(client, conv, client_id="another-message-id").status_code == 403


def test_different_messages_are_different(study, login_as, ai):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    _send(client, conv, "one", "first-message-id")
    _send(client, conv, "two", "second-message-id")
    assert ai.calls == 2


@pytest.mark.parametrize("body", [
    {"message": "hi", "client_message_id": "short"},
    {"message": "hi", "client_message_id": "has spaces in it"},
    {"message": "hi", "client_message_id": 12345678},
    {"message": "   "},
    {},
])
def test_bad_requests_are_400(study, login_as, ai, body):
    resp = login_as(study["patient"]).post(f"/api/conversation/{study['thoughts_conv'].id}/message", json=body)
    assert resp.status_code == 400 and ai.calls == 0


def test_the_database_refuses_a_duplicate_id(study, db):
    conv = study["thoughts_conv"]
    for _ in range(2):
        db.session.add(Message(conversation_id=conv.id, role="user", content="x", timestamp=1, client_message_id=ID))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ── CLOZE-Guard ──

@pytest.fixture
def guard(study, db, monkeypatch):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, guard_enabled=True,
                                        guard_keywords=json.dumps(["hopeless"]),
                                        guard_notify_email="team@example.test"))
    db.session.commit()
    emails = []
    from llm_chat.services import notifications
    monkeypatch.setattr(notifications, "send_guard_email", lambda *a, **k: emails.append(k))
    return emails


def test_the_alert_survives_a_failed_reply_and_a_retry_does_not_repeat_it(study, login_as, ai, guard):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    ai.fail = True
    assert _send(client, conv, "I feel hopeless").status_code == 502
    assert EscalationEvent.query.count() == 1 and len(guard) == 1
    ai.fail = False
    assert _send(client, conv, "I feel hopeless").status_code == 200
    assert EscalationEvent.query.count() == 1 and len(guard) == 1
    assert json.loads(EscalationEvent.query.one().context)["client_message_id"] == ID


def test_a_new_message_with_the_keyword_alerts_again(study, login_as, ai, guard):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    _send(client, conv, "hopeless", "first-message-id")
    _send(client, conv, "still hopeless", "second-message-id")
    assert EscalationEvent.query.count() == 2 and len(guard) == 2


def test_todays_page_alerts_as_before(study, login_as, ai, guard):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    _send(client, conv, "hopeless", client_id=None)
    _send(client, conv, "hopeless", client_id=None)
    assert EscalationEvent.query.count() == 2


def test_reusing_an_id_with_different_text_is_refused_but_scanned(study, login_as, ai, guard):
    conv, client = study["thoughts_conv"], login_as(study["patient"])
    ai.fail = True
    _send(client, conv, "I feel hopeless")
    assert _send(client, conv, "Totally hopeless now").status_code == 409     # a hand-made client
    assert EscalationEvent.query.count() == 2


def test_the_guard_scans_messages_that_are_refused(study, login_as, ai, guard, db):
    from llm_chat.services.conversation_end import end
    end(study["thoughts_conv"], Conversation.TURN_LIMIT)
    db.session.commit()
    resp = _send(login_as(study["patient"]), study["thoughts_conv"], "I feel hopeless")
    assert resp.status_code == 403 and EscalationEvent.query.count() == 1


def test_a_guard_failure_never_blocks_the_message(study, login_as, ai, db, monkeypatch):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, guard_enabled=True,
                                        guard_keywords=json.dumps(["hopeless"])))
    db.session.commit()
    from llm_chat.services import guard

    def broken_insert(*args, **kwargs):
        db.session.add(EscalationEvent(event_type="keyword_match", severity="critical", patient_id=None,
                                       description="x"))
        db.session.flush()                                   # NOT NULL patient_id: fails
    monkeypatch.setattr(guard, "scan_and_escalate", broken_insert)
    assert _send(login_as(study["patient"]), study["thoughts_conv"], "I feel hopeless").status_code == 200
