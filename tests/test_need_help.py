"""Stage 2 Need help?: what the study team says to a participant who's stuck on
an exercise, from a button in the reply box. Each researcher writes a default
in Settings; each study-design chat uses it, has its own, or turns it off.
It's kept apart from Get help now, which is for a crisis.
"""
import json

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import ChatTemplate, Conversation, Guide, Model, ProviderFeatureFlags, ProviderPatient
from llm_chat.models.study_flow import FlowChat, FlowPhase, StudyFlow
from llm_chat.services import need_help

DEFAULT = {
    "heading": "Stuck?",
    "message": "Try the next step.\n\nOr ask Star.",
    "buttons": [
        {"label": "Ask Star", "kind": "send", "value": "Star, can you help me?"},
        {"label": "Read the guide", "kind": "guide", "value": ""},
        {"label": "Email the team", "kind": "link", "value": "mailto:team@example.org"},
    ],
}


@pytest.fixture
def people(app, make_user):
    provider = make_user("prov", role="provider")
    other = make_user("prov2", role="provider")
    patient = make_user("pt")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=patient.id))
    _db.session.commit()
    return {"provider": provider, "other": other, "patient": patient}


# ── Checking what a researcher writes ──────────────────────────

def test_clean_keeps_what_it_needs():
    raw = {"heading": "  Stuck? ", "message": " Try this. ", "extra": "dropped",
           "buttons": [{"label": " Guide ", "kind": "guide", "value": "ignored"}]}
    assert need_help.clean(raw) == {"heading": "Stuck?", "message": "Try this.",
                                    "buttons": [{"label": "Guide", "kind": "guide", "value": ""}]}
    assert need_help.clean(None) is None
    assert need_help.clean({"heading": " ", "message": "", "buttons": []}) is None


@pytest.mark.parametrize("raw, why", [
    ("text", "not an object"),
    ({"heading": "Only a heading"}, "nothing to show"),
    ({"heading": "x" * 81, "message": "m"}, "heading too long"),
    ({"message": "x" * 1001}, "message too long"),
    ({"message": "m", "buttons": [{"label": "a", "kind": "guide"}] * 4}, "too many buttons"),
    ({"buttons": [{"label": "a", "kind": "script", "value": "x"}]}, "unknown kind"),
    ({"buttons": [{"label": "", "kind": "guide"}]}, "no label"),
    ({"buttons": [{"label": "x" * 41, "kind": "guide"}]}, "label too long"),
    ({"buttons": [{"label": "a", "kind": "send", "value": ""}]}, "send with no message"),
    ({"buttons": [{"label": "a", "kind": "send", "value": "x" * 501}]}, "message too long"),
    ({"buttons": [{"label": "a", "kind": "link", "value": "javascript:alert(1)"}]}, "script link"),
    ({"buttons": [{"label": "a", "kind": "link", "value": "http://example.org"}]}, "not https"),
    ({"buttons": [{"label": "a", "kind": "link", "value": "https://exa mple.org"}]}, "a space"),
    ({"buttons": [{"label": "a", "kind": "link", "value": "data:text/html,hi"}]}, "data link"),
    ({"message": ["not text"]}, "not text"),
])
def test_clean_refuses(raw, why):
    with pytest.raises(ValueError):
        need_help.clean(raw)


# ── The researcher's default (Settings) ────────────────────────

def test_the_default_is_saved_read_and_cleared(people, login_as):
    c = login_as(people["provider"])
    assert c.get("/api/provider/my-flags").get_json()["need_help"] is None
    assert c.put("/api/provider/my-flags", json={"need_help": DEFAULT}).status_code == 200
    assert c.get("/api/provider/my-flags").get_json()["need_help"] == DEFAULT
    # Saving another setting leaves it alone.
    assert c.put("/api/provider/my-flags", json={"greeting_text": "Hello"}).status_code == 200
    assert c.get("/api/provider/my-flags").get_json()["need_help"] == DEFAULT
    # Emptying the editor clears it.
    assert c.put("/api/provider/my-flags", json={"need_help": {"heading": "", "message": "", "buttons": []}}).status_code == 200
    assert c.get("/api/provider/my-flags").get_json()["need_help"] is None


def test_a_bad_default_is_refused_and_nothing_changes(people, login_as):
    c = login_as(people["provider"])
    c.put("/api/provider/my-flags", json={"need_help": DEFAULT})
    bad = {"message": "m", "buttons": [{"label": "a", "kind": "link", "value": "javascript:alert(1)"}]}
    resp = c.put("/api/provider/my-flags", json={"need_help": bad, "greeting_text": "Changed"})
    assert resp.status_code == 400 and "https://" in resp.get_json()["error"]
    flags = c.get("/api/provider/my-flags").get_json()
    assert flags["need_help"] == DEFAULT and flags["greeting_text"] != "Changed"


# ── A chat's own (Study Design) ────────────────────────────────

@pytest.fixture
def chat(people):
    model = Model(name="m", provider="local", model_identifier="m")
    _db.session.add(model)
    flow = StudyFlow(provider_id=people["provider"].id, name="Practice", flow_type="always")
    _db.session.add(flow)
    _db.session.flush()
    phase = FlowPhase(flow_id=flow.id, name="Practice", order_index=0)
    _db.session.add(phase)
    _db.session.flush()
    c = FlowChat(phase_id=phase.id, title="Thought records", model_id=model.id)
    _db.session.add(c)
    _db.session.commit()
    return c


def test_a_chat_uses_the_default_has_its_own_or_none(people, login_as, chat):
    c = login_as(people["provider"])
    url = f"/api/provider/chats/{chat.id}"
    assert c.get(f"/api/provider/flows/{chat.phase.flow.id}").get_json()["phases"][0]["chats"][0]["need_help_mode"] == "default"

    own = {"message": "Just for this chat.", "buttons": []}
    saved = c.put(url, json={"need_help_mode": "custom", "need_help": own}).get_json()
    assert (saved["need_help_mode"], saved["need_help"]) == ("custom", {"heading": "", **own})

    saved = c.put(url, json={"need_help_mode": "off"}).get_json()
    assert saved["need_help_mode"] == "off"
    assert saved["need_help"]["message"] == "Just for this chat."   # kept, for switching back

    saved = c.put(url, json={"need_help_mode": "default"}).get_json()
    assert saved["need_help_mode"] == "default"
    assert _db.session.get(FlowChat, chat.id).need_help_mode is None


@pytest.mark.parametrize("body", [
    {"need_help_mode": "custom"},                                              # nothing written
    {"need_help_mode": "custom", "need_help": {"message": "", "buttons": []}},
    {"need_help_mode": "sometimes"},
    {"need_help_mode": "custom", "need_help": {"buttons": [{"label": "a", "kind": "link", "value": "ftp://x"}]}},
])
def test_a_chats_need_help_is_checked(people, login_as, chat, body):
    resp = login_as(people["provider"]).put(f"/api/provider/chats/{chat.id}", json=body)
    assert resp.status_code == 400
    stored = _db.session.get(FlowChat, chat.id)
    assert (stored.need_help_mode, stored.need_help) == (None, None)


def test_a_new_chat_can_have_its_own(people, login_as, chat):
    resp = login_as(people["provider"]).post(f"/api/provider/phases/{chat.phase_id}/chats", json={
        "title": "Another", "model_id": chat.model_id,
        "need_help_mode": "custom", "need_help": {"message": "Hi.", "buttons": []}})
    assert resp.status_code in (200, 201), resp.get_json()
    assert resp.get_json()["need_help_mode"] == "custom"


# ── What the participant sees ──────────────────────────────────

@pytest.fixture
def enrolled(people, login_as, chat, v2):
    """The participant enrolled in the chat's flow, with a started
    conversation, and the researcher's default written."""
    flags = ProviderFeatureFlags(provider_id=people["provider"].id, need_help=json.dumps(DEFAULT))
    _db.session.add(flags)
    _db.session.commit()
    login_as(people["provider"]).post(f"/api/provider/flows/{chat.phase.flow.id}/enroll",
                                      json={"patient_ids": [people["patient"].id]})
    template = ChatTemplate.query.filter_by(flow_chat_id=chat.id).one()
    conv = Conversation(user_id=people["patient"].id, title=template.title, model_id=chat.model_id,
                        window_id=template.window_id, template_id=template.id, consent_provided=True)
    _db.session.add(conv)
    _db.session.commit()
    return {"conv": conv, "chat": chat, "flags": flags, **people}


def page(client, conv):
    return client.get(f"/exercise/{conv.id}").get_data(as_text=True)


def test_the_default_shows_in_the_reply_box(enrolled, login_as):
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert "data-need-help-open" in html and 'id="need-help-dialog"' in html
    assert "participant/need-help.js" in html
    assert "Stuck?" in html and "Try the next step." in html and "Or ask Star." in html
    assert 'data-need-help-send="Star, can you help me?"' in html
    assert 'href="mailto:team@example.org"' in html and 'rel="noopener noreferrer"' in html
    # The chat has no guide, so there's no guide button.
    assert "Read the guide" not in html and "data-need-help-guide" not in html
    # Get help now is always one tap away, and stays its own dialog.
    assert html.count("data-help-open") >= 2 and 'id="help-dialog"' in html


def test_a_guide_button_shows_when_the_chat_has_a_guide(enrolled, login_as):
    guide = Guide(owner_id=enrolled["provider"].id, title="The CBT model", body_md="Hello")
    _db.session.add(guide)
    _db.session.flush()
    enrolled["chat"].guide_id = guide.id
    _db.session.commit()
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert "Read the guide" in html and "data-need-help-guide" in html


def test_a_chats_own_replaces_the_default_and_edits_reach_it(enrolled, login_as):
    c = login_as(enrolled["patient"])
    enrolled["chat"].need_help_mode = "custom"
    enrolled["chat"].need_help = json.dumps({"heading": "", "message": "Only here.", "buttons": []})
    _db.session.commit()
    html = page(c, enrolled["conv"])
    assert "Only here." in html and "Try the next step." not in html
    assert need_help.DEFAULT_HEADING in html          # no heading written

    enrolled["chat"].need_help = json.dumps({"heading": "", "message": "Edited.", "buttons": []})
    _db.session.commit()
    assert "Edited." in page(c, enrolled["conv"])


@pytest.mark.parametrize("change", ["off", "no default", "another researcher", "not started"])
def test_no_need_help_button(enrolled, login_as, change):
    if change == "off":
        enrolled["chat"].need_help_mode = "off"
    elif change == "no default":
        enrolled["flags"].need_help = None
    elif change == "another researcher":
        # The chat isn't from the participant's researcher any more, and the
        # new researcher has no default.
        link = ProviderPatient.query.filter_by(patient_id=enrolled["patient"].id).one()
        link.provider_id = enrolled["other"].id
    else:
        enrolled["conv"].consent_provided = False
    _db.session.commit()
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert "data-need-help-open" not in html and "need-help-dialog" not in html


def test_only_a_guide_button_and_no_guide_means_no_button(enrolled, login_as):
    enrolled["flags"].need_help = json.dumps({"heading": "Stuck?", "message": "",
                                              "buttons": [{"label": "Guide", "kind": "guide", "value": ""}]})
    _db.session.commit()
    assert "data-need-help-open" not in page(login_as(enrolled["patient"]), enrolled["conv"])


def test_what_the_team_writes_is_escaped(enrolled, login_as):
    enrolled["flags"].need_help = json.dumps({
        "heading": "<b>Stuck</b>", "message": "<script>alert(1)</script>",
        "buttons": [{"label": "<i>Go</i>", "kind": "send", "value": '"><img src=x onerror=alert(1)>'}]})
    _db.session.commit()
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html
    assert "&lt;b&gt;Stuck&lt;/b&gt;" in html and "&lt;i&gt;Go&lt;/i&gt;" in html
