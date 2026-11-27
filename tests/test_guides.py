"""Stage 2 guides: a researcher's Markdown pages, attached to chats, read by
participants beside the chat, and (only when the team turns it on) given to
the model after the chat's prompt.

Images in a guide must come from the researcher's own media library. That's
checked here on save; the participant's page also drops any other image
(renderGuideMarkdown in static/js/shared.js).
"""
import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import (AdminSettings, ChatTemplate, Conversation, Guide, MediaAsset, Model,
                             ProviderPatient)
from llm_chat.models.study_flow import FlowChat, FlowPhase, StudyFlow
from llm_chat.services.llm_interface import LLMInterface


@pytest.fixture
def people(app, make_user):
    provider = make_user("prov", role="provider")
    other = make_user("prov2", role="provider")
    patient = make_user("pt")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=patient.id))
    _db.session.commit()
    return {"provider": provider, "other": other, "patient": patient}


def image(owner, kind=MediaAsset.KIND_IMAGE):
    asset = MediaAsset(owner_id=owner.id, kind=kind, status=MediaAsset.STATUS_READY, label="Picture")
    _db.session.add(asset)
    _db.session.commit()
    return asset


def make_guide(owner, title="The CBT model", body="# Thoughts\n\nThey affect feelings."):
    guide = Guide(owner_id=owner.id, title=title, body_md=body)
    _db.session.add(guide)
    _db.session.commit()
    return guide


# ── The researcher's API ───────────────────────────────────────

def test_writing_listing_and_removing_guides(people, login_as):
    c = login_as(people["provider"])
    created = c.post("/api/provider/guides", json={"title": " The CBT model ", "body_md": "# Hello"})
    assert created.status_code == 201
    guide = created.get_json()
    assert (guide["title"], guide["body_md"], guide["used_by"]) == ("The CBT model", "# Hello", [])

    edited = c.put(f"/api/provider/guides/{guide['id']}", json={"body_md": "# Hello again"}).get_json()
    assert edited["body_md"] == "# Hello again"
    assert [g["title"] for g in c.get("/api/provider/guides").get_json()["guides"]] == ["The CBT model"]

    assert c.delete(f"/api/provider/guides/{guide['id']}", json={}).status_code == 200
    assert c.get("/api/provider/guides").get_json()["guides"] == []
    assert _db.session.get(Guide, guide["id"]).deleted_at is not None


@pytest.mark.parametrize("body, why", [
    ({"title": ""}, "no title"),
    ({"title": "x" * 121}, "title too long"),
    ({"title": "Fine", "body_md": "y" * 20_001}, "guide too long"),
    ({"title": "Fine", "body_md": ["not text"]}, "not text"),
])
def test_guide_input_is_checked(people, login_as, body, why):
    assert login_as(people["provider"]).post("/api/provider/guides", json=body).status_code == 400, why


def test_images_must_come_from_your_own_library(people, login_as):
    mine, theirs = image(people["provider"]), image(people["other"])
    video = image(people["provider"], kind=MediaAsset.KIND_VIDEO)
    c = login_as(people["provider"])

    ok = c.post("/api/provider/guides", json={"title": "A", "body_md": f"![Sky](/media/{mine.public_id})\n\n"
                                                                        f'<img src="/media/{mine.public_id}?r=thumb">'})
    assert ok.status_code == 201
    for body in (f"![x](/media/{theirs.public_id})",                       # another researcher's
                 f"![x](/media/{video.public_id})",                        # not an image
                 "![x](https://example.com/tracker.png)",                  # another site
                 '<img src="https://example.com/x.png">',                  # the same, as HTML
                 "![x](data:image/png;base64,AAAA)",                       # inline data
                 "![x](/media/not-a-real-id)"):
        assert c.post("/api/provider/guides", json={"title": "B", "body_md": body}).status_code == 400, body


def test_an_image_already_in_a_guide_can_stay_after_leaving_the_library(people, login_as):
    picture = image(people["provider"])
    c = login_as(people["provider"])
    guide_id = c.post("/api/provider/guides", json={"title": "A", "body_md": f"![p](/media/{picture.public_id})"}).get_json()["id"]
    picture.deleted_at = 1.0
    _db.session.commit()
    resp = c.put(f"/api/provider/guides/{guide_id}", json={"body_md": f"New intro.\n\n![p](/media/{picture.public_id})"})
    assert resp.status_code == 200


def test_another_researchers_guides_dont_exist_for_you(people, login_as):
    guide = make_guide(people["provider"])
    c = login_as(people["other"])
    assert c.get("/api/provider/guides").get_json()["guides"] == []
    assert c.put(f"/api/provider/guides/{guide.id}", json={"title": "Mine"}).status_code == 404
    assert c.delete(f"/api/provider/guides/{guide.id}", json={}).status_code == 404
    assert login_as(people["patient"]).get("/api/provider/guides").status_code == 403


# ── A chat's guide ─────────────────────────────────────────────

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


def test_attaching_a_guide_to_a_chat(people, login_as, chat):
    guide = make_guide(people["provider"])
    c = login_as(people["provider"])

    saved = c.put(f"/api/provider/chats/{chat.id}", json={"guide_id": guide.id, "guide_opens_on_start": True,
                                                         "guide_to_model": False}).get_json()
    assert (saved["guide_id"], saved["guide_opens_on_start"], saved["guide_to_model"]) == (guide.id, True, False)
    used_by = c.get("/api/provider/guides").get_json()["guides"][0]["used_by"]
    assert used_by == [{"chat_id": chat.id, "title": "Thought records", "flow": "Practice"}]
    assert c.put(f"/api/provider/chats/{chat.id}", json={"guide_id": None}).get_json()["guide_id"] is None


@pytest.mark.parametrize("make_body", [
    lambda mine, theirs, gone: {"guide_id": theirs},           # another researcher's
    lambda mine, theirs, gone: {"guide_id": gone},             # removed
    lambda mine, theirs, gone: {"guide_id": "1"},              # not an id
    lambda mine, theirs, gone: {"guide_to_model": "yes"},      # not true or false
])
def test_a_chats_guide_is_checked(people, login_as, chat, make_body):
    mine, theirs = make_guide(people["provider"]), make_guide(people["other"])
    gone = make_guide(people["provider"], title="Old")
    gone.deleted_at = 1.0
    _db.session.commit()
    resp = login_as(people["provider"]).put(f"/api/provider/chats/{chat.id}", json=make_body(mine.id, theirs.id, gone.id))
    assert resp.status_code == 400
    assert _db.session.get(FlowChat, chat.id).guide_id is None


# ── What the participant sees, and what the model is given ─────

@pytest.fixture
def enrolled(people, login_as, chat, v2, monkeypatch):
    """The participant enrolled in a flow whose chat has a guide, with a
    started conversation. The model's calls are recorded."""
    guide = make_guide(people["provider"], body="# Thoughts\n\nThey affect <b>feelings</b>.")
    chat.guide_id = guide.id
    _db.session.commit()
    login_as(people["provider"]).post(f"/api/provider/flows/{chat.phase.flow.id}/enroll",
                                      json={"patient_ids": [people["patient"].id]})
    template = ChatTemplate.query.filter_by(flow_chat_id=chat.id).one()
    conv = Conversation(user_id=people["patient"].id, title=template.title, model_id=chat.model_id,
                        window_id=template.window_id, template_id=template.id, consent_provided=True,
                        system_prompt_content="THE COMPOSED PROMPT")
    _db.session.add(conv)
    _db.session.commit()

    prompts = []

    def call(cls, model, history, system_prompt=None, config_override=None, raise_on_error=False):
        prompts.append(system_prompt)
        return "A reply.", 0.01

    monkeypatch.setattr(LLMInterface, "call_llm", classmethod(call))
    return {"conv": conv, "chat": chat, "guide": guide, "prompts": prompts, **people}


def page(client, conv):
    return client.get(f"/exercise/{conv.id}").get_data(as_text=True)


def test_the_guide_shows_in_its_own_tab_beside_the_notebook(enrolled, login_as):
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert 'id="tab-guide"' in html and 'id="tab-notebook"' in html
    assert 'data-panel-open="guide"' in html
    assert "The CBT model" in html
    # The text reaches the page escaped; the browser renders it with the guide sanitiser.
    assert "They affect &lt;b&gt;feelings&lt;/b&gt;." in html
    assert "data-open-guide" not in html


def test_a_guide_can_open_when_the_chat_starts(enrolled, login_as):
    enrolled["chat"].guide_opens_on_start = True
    _db.session.commit()
    assert f'data-open-guide="{enrolled["conv"].template_id}"' in page(login_as(enrolled["patient"]), enrolled["conv"])


def test_with_saving_off_the_panel_holds_only_the_guide(enrolled, login_as):
    _db.session.add(AdminSettings(setting_name="users_can_save_selections", setting_value="false"))
    _db.session.commit()
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert '<aside id="panel"' in html and 'id="pane-guide"' in html
    assert 'id="pane-notebook"' not in html and 'role="tablist"' not in html and "data-save-to" not in html
    assert "participant/panel.js" in html and "select-save.js" not in html


@pytest.mark.parametrize("change", ["removed", "no guide", "another researcher"])
def test_no_guide_means_no_guide_tab(enrolled, login_as, change):
    if change == "removed":
        enrolled["guide"].deleted_at = 1.0
    elif change == "no guide":
        enrolled["chat"].guide_id = None
    else:
        link = ProviderPatient.query.filter_by(patient_id=enrolled["patient"].id).one()
        link.provider_id = enrolled["other"].id
    _db.session.commit()
    html = page(login_as(enrolled["patient"]), enrolled["conv"])
    assert 'id="pane-guide"' not in html and 'data-panel-open="guide"' not in html
