"""The greeting an empty chat shows: researcher default, per-chat override,
read live so edits reach participants already enrolled."""
import io

import pytest
from PIL import Image

from llm_chat.extensions import db as _db
from llm_chat.models import (ChatTemplate, Conversation, FlowChat, FlowPhase, Model, ProviderPatient,
                             StudyFlow)
from llm_chat.services.greeting import DEFAULT_GREETING_TEXT

JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def media_dir(app, tmp_path):
    app.config["MEDIA_LOCAL_DIR"] = str(tmp_path)
    app.extensions.pop("cloze_media_store", None)


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
    """An always-available flow with two character chats."""
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


def upload_image(client, label):
    out = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 120, 200)).save(out, "PNG")
    resp = client.post("/api/provider/media", headers={"X-Requested-With": "fetch"},
                       content_type="multipart/form-data",
                       data={"file": (io.BytesIO(out.getvalue()), f"{label}.png"),
                             "label": label, "alt_text": f"Portrait of {label}"})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def enroll(login_as, provider, patient, flow):
    resp = login_as(provider).post(f"/api/provider/flows/{flow.id}/enroll", json={"patient_ids": [patient.id]})
    assert resp.status_code == 200, resp.get_json()


def start_chat(patient, title):
    template = ChatTemplate.query.filter_by(title=title).one()
    conv = Conversation(user_id=patient.id, model_id=template.model_id, title=title,
                        window_id=template.window_id, template_id=template.id)
    _db.session.add(conv)
    _db.session.commit()
    return conv


def greeting(login_as, patient, conv):
    resp = login_as(patient).get(f"/api/conversation/{conv.id}")
    assert resp.status_code == 200
    return resp.get_json()["greeting"]


def chat_id(title):
    return FlowChat.query.filter_by(title=title).one().id


def test_built_in_greeting_when_nothing_is_set(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    assert greeting(login_as, patient, start_chat(patient, "Ann")) == {
        "text": DEFAULT_GREETING_TEXT, "image_url": None, "alt": ""}


def test_chat_override_then_researcher_default_for_each_part(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    researcher = login_as(provider)
    default_img = upload_image(researcher, "Logo")
    ann_img = upload_image(researcher, "Ann")

    resp = researcher.put("/api/provider/my-flags",
                          json={"greeting_text": "Hi! Say hello to begin.", "greeting_asset_id": default_img["id"]})
    assert resp.status_code == 200
    # Ann overrides only the image; Alex overrides only the text.
    assert researcher.put(f"/api/provider/chats/{chat_id('Ann')}",
                          json={"greeting_asset_id": ann_img["id"]}).status_code == 200
    assert researcher.put(f"/api/provider/chats/{chat_id('Alex')}",
                          json={"greeting_text": "Alex is ready when you are."}).status_code == 200

    ann = greeting(login_as, patient, start_chat(patient, "Ann"))
    alex = greeting(login_as, patient, start_chat(patient, "Alex"))
    assert ann == {"text": "Hi! Say hello to begin.", "image_url": ann_img["url"], "alt": "Portrait of Ann"}
    assert alex == {"text": "Alex is ready when you are.", "image_url": default_img["url"], "alt": "Portrait of Logo"}
    # ...and the participant can load the image it points to.
    assert login_as(patient).get(ann["image_url"]).status_code == 200


def test_edits_after_enrollment_reach_enrolled_participants(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    conv = start_chat(patient, "Ann")
    assert greeting(login_as, patient, conv)["text"] == DEFAULT_GREETING_TEXT

    login_as(provider).put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "I'm Ann."})
    assert greeting(login_as, patient, conv)["text"] == "I'm Ann."


def test_clearing_an_override_falls_back(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    researcher = login_as(provider)
    researcher.put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "I'm Ann."})
    researcher.put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "  "})
    assert _db.session.get(FlowChat, chat_id("Ann")).greeting_text is None
    assert greeting(login_as, patient, start_chat(patient, "Ann"))["text"] == DEFAULT_GREETING_TEXT


def test_greeting_text_is_limited(login_as, provider, flow):
    resp = login_as(provider).put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "x" * 201})
    assert resp.status_code == 400
    assert login_as(provider).put("/api/provider/my-flags", json={"greeting_text": 5}).status_code == 400


def test_another_researchers_image_is_refused(login_as, make_user, provider, flow):
    other = make_user("other", role="provider")
    theirs = upload_image(login_as(other), "Theirs")
    researcher = login_as(provider)
    assert researcher.put(f"/api/provider/chats/{chat_id('Ann')}",
                          json={"greeting_asset_id": theirs["id"]}).status_code == 400
    assert researcher.put("/api/provider/my-flags", json={"greeting_asset_id": theirs["id"]}).status_code == 400
    resp = researcher.post(f"/api/provider/phases/{FlowPhase.query.one().id}/chats",
                           json={"title": "New", "model_id": FlowChat.query.first().model_id,
                                 "greeting_asset_id": theirs["id"]})
    assert resp.status_code == 400
    assert _db.session.get(FlowChat, chat_id("Ann")).greeting_asset_id is None


def test_greeting_follows_the_participants_current_researcher(login_as, make_user, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    conv = start_chat(patient, "Ann")
    login_as(provider).put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "I'm Ann."})
    assert greeting(login_as, patient, conv)["text"] == "I'm Ann."

    # Moved to another researcher (a direct database change; the app has no route for it).
    other = make_user("other", role="provider")
    ProviderPatient.query.filter_by(patient_id=patient.id).one().provider_id = other.id
    _db.session.commit()
    login_as(other).put("/api/provider/my-flags", json={"greeting_text": "Welcome from the new team."})
    assert greeting(login_as, patient, conv)["text"] == "Welcome from the new team."


def test_a_removed_image_stays_on_chats_already_using_it(login_as, provider, flow):
    researcher = login_as(provider)
    ann = chat_id("Ann")
    img, other_img = upload_image(researcher, "Ann"), upload_image(researcher, "Old")
    researcher.put(f"/api/provider/chats/{ann}", json={"greeting_asset_id": img["id"]})
    researcher.put("/api/provider/my-flags", json={"greeting_asset_id": img["id"]})
    for asset in (img, other_img):
        researcher.delete(f"/api/provider/media/{asset['id']}", headers=JSON_HEADERS)

    # The edit forms send the current image back with every save.
    resp = researcher.put(f"/api/provider/chats/{ann}",
                          json={"title": "Ann (week 2)", "greeting_asset_id": img["id"].upper()})
    assert resp.status_code == 200
    assert resp.get_json()["greeting_asset"]["id"] == img["id"]
    assert researcher.put("/api/provider/my-flags",
                          json={"greeting_text": "Hi.", "greeting_asset_id": img["id"]}).status_code == 200
    # Choosing a removed image anew is still refused.
    assert researcher.put(f"/api/provider/chats/{ann}",
                          json={"greeting_asset_id": other_img["id"]}).status_code == 400


def test_deleting_a_study_chat_falls_back_to_the_researcher_default(login_as, provider, patient, flow):
    enroll(login_as, provider, patient, flow)
    conv = start_chat(patient, "Ann")
    researcher = login_as(provider)
    researcher.put("/api/provider/my-flags", json={"greeting_text": "Default hello."})
    researcher.put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_text": "I'm Ann."})

    assert researcher.delete(f"/api/provider/chats/{chat_id('Ann')}", headers=JSON_HEADERS).status_code == 200
    assert greeting(login_as, patient, conv)["text"] == "Default hello."


def test_settings_and_study_design_return_the_greeting(login_as, provider, flow):
    researcher = login_as(provider)
    img = upload_image(researcher, "Ann")
    researcher.put("/api/provider/my-flags", json={"greeting_text": "Hello.", "greeting_asset_id": img["id"]})
    flags = researcher.get("/api/provider/my-flags").get_json()
    assert flags["greeting_text"] == "Hello."
    assert flags["greeting_asset"]["id"] == img["id"]

    researcher.put(f"/api/provider/chats/{chat_id('Ann')}", json={"greeting_asset_id": img["id"]})
    chat = _db.session.get(FlowChat, chat_id("Ann")).to_dict()
    assert chat["greeting_asset"]["id"] == img["id"]
    assert "storage_key" not in str(chat)
