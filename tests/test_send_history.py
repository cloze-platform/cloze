"""What the model is sent: the latest 20 messages, then the new one, once."""

from llm_chat.models import Message
from llm_chat.services.llm_interface import LLMInterface


def _send_and_capture(study, db, login_as, monkeypatch, extra):
    seen = []
    monkeypatch.setattr(LLMInterface, "call_llm",
                        staticmethod(lambda model, history, system_prompt=None, *a, **k: (seen.append(history) or "ok", 0.1)))
    conv = study["thoughts_conv"]                      # 4 messages: "message 0" to "message 3"
    for i in range(extra):
        db.session.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant",
                               content=f"extra {i}", timestamp=1_800_000_000 + i))
    db.session.commit()
    assert login_as(study["patient"]).post(f"/api/conversation/{conv.id}/message",
                                           json={"message": "newest"}).status_code == 200
    return [m["content"] for m in seen[0]]


def test_a_short_conversation_sends_everything_and_the_new_message_once(study, db, login_as, monkeypatch):
    sent = _send_and_capture(study, db, login_as, monkeypatch, 0)
    assert sent == ["message 0", "message 1", "message 2", "message 3", "newest"]


def test_a_long_conversation_sends_the_latest_twenty(study, db, login_as, monkeypatch):
    sent = _send_and_capture(study, db, login_as, monkeypatch, 30)    # 34 saved
    assert sent == [f"extra {i}" for i in range(10, 30)] + ["newest"]
