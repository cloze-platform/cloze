"""Stage 2 speakers: a researcher's speakers, each chat's cast, and splitting
a reply into the parts each speaker says.

Speakers only change how a reply is shown: the stored reply, and the history
sent back to the model, stay exactly as the model wrote them (the team's
prompt has to work the same in Cloze as anywhere else).
"""
import json

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import MediaAsset, Model, ProviderPatient, Speaker
from llm_chat.models.study_flow import FlowChat, FlowPhase, StudyFlow
from llm_chat.services.speakers import cast_for_template, split_reply


# ── The parser ─────────────────────────────────────────────────

SKY, STAR = Speaker(name="Sky"), Speaker(name="Star")
CAST = [SKY, STAR]


def parts(text, cast=CAST, main=None):
    return [(p.speaker.name if p.speaker else None, p.text) for p in split_reply(text, cast, main)]


@pytest.mark.parametrize("text, main, expected", [
    # Each tagged line starts that speaker's part.
    ("Star: Hello.\nSky: Hi!", None, [("Star", "Hello."), ("Sky", "Hi!")]),
    # Bold names, any case, extra spaces.
    ("**Star:** Hello.\n**sky**: Hi!\n  STAR :  Bye.", None, [("Star", "Hello."), ("Sky", "Hi!"), ("Star", "Bye.")]),
    # Untagged lines continue the part they follow, across paragraphs.
    ("Star: One.\n\nTwo.\nSky: Three.", None, [("Star", "One.\n\nTwo."), ("Sky", "Three.")]),
    # Text before the first name goes to the main speaker...
    ("Welcome back.\nSky: Hi!", STAR, [("Star", "Welcome back."), ("Sky", "Hi!")]),
    # ...or shows unnamed when there's none.
    ("Welcome back.\nSky: Hi!", None, [(None, "Welcome back."), ("Sky", "Hi!")]),
    # An untagged reply is all the main speaker's.
    ("Just one voice.", STAR, [("Star", "Just one voice.")]),
    # The same speaker twice in a row is one part.
    ("Sky: a\nSky: b", None, [("Sky", "a\n\nb")]),
    # Only the cast's names, only at the start of a line, only before a colon.
    ("Star: Look at the Sky: it's blue.\nNarrator: (pause)\nSkyler: hi\nYou: ok", None,
     [("Star", "Look at the Sky: it's blue.\nNarrator: (pause)\nSkyler: hi\nYou: ok")]),
    # A name on its own line starts the part that follows it.
    ("Sky:\nI'm here.", None, [("Sky", "I'm here.")]),
    # Markdown inside a part is kept for the page to render.
    ("Star: Try this:\n- breathe in\n- breathe out", None, [("Star", "Try this:\n- breathe in\n- breathe out")]),
])
def test_split_reply(text, main, expected):
    assert parts(text, main=main) == expected


def test_no_cast_means_the_reply_as_it_is():
    text = "Star: Hello.\nSky: Hi!"
    assert parts(text, cast=[]) == [(None, text)]


def test_a_longer_name_wins_over_its_prefix():
    starla = Speaker(name="Starla")
    assert parts("Starla: hi\nStar: hey", cast=[STAR, starla]) == [("Starla", "hi"), ("Star", "hey")]


# ── The researcher's API ───────────────────────────────────────

@pytest.fixture
def people(app, make_user):
    provider = make_user("prov", role="provider")
    other = make_user("prov2", role="provider")
    patient = make_user("pt")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=patient.id))
    _db.session.commit()
    return {"provider": provider, "other": other, "patient": patient}


def image(owner, label="Face", kind=MediaAsset.KIND_IMAGE):
    asset = MediaAsset(owner_id=owner.id, kind=kind, status=MediaAsset.STATUS_READY, label=label)
    _db.session.add(asset)
    _db.session.commit()
    return asset


def test_creating_listing_and_editing_speakers(people, login_as):
    face = image(people["provider"])
    c = login_as(people["provider"])

    resp = c.post("/api/provider/speakers", json={"name": " Sky ", "role": "Practice student", "picture_id": face.public_id})
    assert resp.status_code == 201
    sky = resp.get_json()
    assert (sky["name"], sky["role"], sky["picture"]["id"]) == ("Sky", "Practice student", face.public_id)
    c.post("/api/provider/speakers", json={"name": "Star"})

    assert [s["name"] for s in c.get("/api/provider/speakers").get_json()["speakers"]] == ["Sky", "Star"]
    edited = c.put(f"/api/provider/speakers/{sky['id']}", json={"role": "", "picture_id": None}).get_json()
    assert (edited["role"], edited["picture"]) == (None, None)


@pytest.mark.parametrize("body, why", [
    ({"name": ""}, "blank"),
    ({"name": "x" * 41}, "too long"),
    ({"name": "Sky: the student"}, "a colon would break matching"),
    ({"name": "sky"}, "names are unique, ignoring case"),
    ({"name": "Moon", "role": "r" * 61}, "role too long"),
    ({"name": "Moon", "role": 7}, "role not text"),
])
def test_speaker_input_is_checked(people, login_as, body, why):
    c = login_as(people["provider"])
    c.post("/api/provider/speakers", json={"name": "Sky"})
    assert c.post("/api/provider/speakers", json=body).status_code == 400, why


def test_a_picture_must_be_an_image_in_your_own_library(people, login_as):
    c = login_as(people["provider"])
    theirs = image(people["other"])
    video = image(people["provider"], kind=MediaAsset.KIND_VIDEO)
    assert c.post("/api/provider/speakers", json={"name": "Sky", "picture_id": theirs.public_id}).status_code == 400
    assert c.post("/api/provider/speakers", json={"name": "Sky", "picture_id": video.public_id}).status_code == 400
    assert c.post("/api/provider/speakers", json={"name": "Sky", "picture_id": "not-an-id"}).status_code == 400


def test_another_researchers_speakers_dont_exist_for_you(people, login_as):
    sky_id = login_as(people["provider"]).post("/api/provider/speakers", json={"name": "Sky"}).get_json()["id"]
    c = login_as(people["other"])
    assert c.get("/api/provider/speakers").get_json()["speakers"] == []
    assert c.put(f"/api/provider/speakers/{sky_id}", json={"name": "Mine"}).status_code == 404
    assert c.delete(f"/api/provider/speakers/{sky_id}", json={}).status_code == 404
    # The same name is fine for a different researcher.
    assert c.post("/api/provider/speakers", json={"name": "Sky"}).status_code == 201
    # Participants can't use the API at all.
    assert login_as(people["patient"]).get("/api/provider/speakers").status_code == 403


def test_removing_a_speaker_frees_its_name(people, login_as):
    c = login_as(people["provider"])
    sky_id = c.post("/api/provider/speakers", json={"name": "Sky"}).get_json()["id"]
    assert c.delete(f"/api/provider/speakers/{sky_id}", json={}).status_code == 200
    assert c.get("/api/provider/speakers").get_json()["speakers"] == []
    assert _db.session.get(Speaker, sky_id).deleted_at is not None
    assert c.post("/api/provider/speakers", json={"name": "Sky"}).status_code == 201


def test_reordering_speakers(people, login_as):
    c = login_as(people["provider"])
    a, b = (c.post("/api/provider/speakers", json={"name": n}).get_json()["id"] for n in ("Sky", "Star"))
    assert [s["name"] for s in c.put("/api/provider/speaker-order", json={"speaker_ids": [b, a]}).get_json()["speakers"]] == ["Star", "Sky"]
    assert c.put("/api/provider/speaker-order", json={"speaker_ids": [a]}).status_code == 400
    assert c.put("/api/provider/speaker-order", json={"speaker_ids": [a, a]}).status_code == 400


# ── A chat's cast ──────────────────────────────────────────────

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
    c = FlowChat(phase_id=phase.id, title="Meet Sky and Star", model_id=model.id)
    _db.session.add(c)
    _db.session.commit()
    return c


def speakers(owner, *names):
    made = [Speaker(owner_id=owner.id, name=n, order_index=i) for i, n in enumerate(names)]
    _db.session.add_all(made)
    _db.session.commit()
    return made


def test_setting_a_chats_cast_and_main_speaker(people, login_as, chat):
    sky, star = speakers(people["provider"], "Sky", "Star")
    c = login_as(people["provider"])

    saved = c.put(f"/api/provider/chats/{chat.id}", json={"speaker_ids": [star.id, sky.id], "main_speaker_id": star.id}).get_json()

    assert (saved["speaker_ids"], saved["main_speaker_id"]) == ([star.id, sky.id], star.id)
    # Taking the main speaker out of the cast clears it.
    saved = c.put(f"/api/provider/chats/{chat.id}", json={"speaker_ids": [sky.id]}).get_json()
    assert (saved["speaker_ids"], saved["main_speaker_id"]) == ([sky.id], None)
    saved = c.put(f"/api/provider/chats/{chat.id}", json={"speaker_ids": []}).get_json()
    assert (saved["speaker_ids"], chat.speaker_ids) == ([], None)


@pytest.mark.parametrize("make_body", [
    lambda sky, star, theirs: {"speaker_ids": [sky, theirs]},             # another researcher's
    lambda sky, star, theirs: {"speaker_ids": [sky, sky]},                # twice
    lambda sky, star, theirs: {"speaker_ids": [sky, True]},               # not an id
    lambda sky, star, theirs: {"speaker_ids": "sky"},                     # not a list
    lambda sky, star, theirs: {"speaker_ids": [sky], "main_speaker_id": star},  # main not in the cast
])
def test_a_cast_is_checked(people, login_as, chat, make_body):
    sky, star = speakers(people["provider"], "Sky", "Star")
    (theirs,) = speakers(people["other"], "Moon")
    resp = login_as(people["provider"]).put(f"/api/provider/chats/{chat.id}", json=make_body(sky.id, star.id, theirs.id))
    assert resp.status_code == 400
    assert _db.session.get(FlowChat, chat.id).speaker_ids is None


def test_the_cast_read_for_a_participant_skips_removed_and_foreign_speakers(people, login_as, chat):
    sky, star, gone = speakers(people["provider"], "Sky", "Star", "Gone")
    chat.speaker_ids = json.dumps([star.id, gone.id, sky.id])
    chat.main_speaker_id = gone.id
    gone.deleted_at = 1.0
    _db.session.commit()

    class Template:
        flow_chat = chat

    cast, main = cast_for_template(Template, people["patient"])
    assert ([s.name for s in cast], main) == (["Star", "Sky"], None)

    # A participant whose researcher is someone else gets no cast at all.
    stranger = ProviderPatient.query.filter_by(patient_id=people["patient"].id).one()
    stranger.provider_id = people["other"].id
    _db.session.commit()
    assert cast_for_template(Template, people["patient"]) == ([], None)


# ── What the participant sees ─────────────────────────────────

from llm_chat.models import ChatTemplate, Conversation, Message, SavedSelection  # noqa: E402
from llm_chat.services.llm_interface import LLMInterface  # noqa: E402


@pytest.fixture
def enrolled(people, login_as, chat, v2, monkeypatch):
    """The participant enrolled in a flow whose chat has Star (main) and Sky,
    with a started conversation. The model always answers as both."""
    face = image(people["provider"], label="Star's face")
    star, sky = speakers(people["provider"], "Star", "Sky")
    star.role, sky.role, star.picture_asset_id = "Facilitator", "Practice student", face.id
    chat.speaker_ids, chat.main_speaker_id = json.dumps([star.id, sky.id]), star.id
    _db.session.commit()
    resp = login_as(people["provider"]).post(f"/api/provider/flows/{chat.phase.flow.id}/enroll",
                                             json={"patient_ids": [people["patient"].id]})
    assert resp.status_code == 200
    template = ChatTemplate.query.filter_by(flow_chat_id=chat.id).one()
    conv = Conversation(user_id=people["patient"].id, title=template.title, model_id=chat.model_id,
                        window_id=template.window_id, template_id=template.id, consent_provided=True)
    _db.session.add(conv)
    _db.session.commit()

    histories = []

    def call(cls, model, history, system_prompt=None, config_override=None, raise_on_error=False):
        histories.append(history)
        return "Star: Welcome back.\n**Sky:** Hi! I'm practising too.", 0.01

    monkeypatch.setattr(LLMInterface, "call_llm", classmethod(call))
    return {"conv": conv, "template": template, "star": star, "sky": sky, "face": face, "histories": histories,
            **people}


def send(client, conv, text="hello"):
    return client.post(f"/api/conversation/{conv.id}/message",
                       json={"message": text, "client_message_id": f"id-{text}"})


def test_a_reply_comes_back_as_each_speakers_part(enrolled, login_as):
    c = login_as(enrolled["patient"])
    body = send(c, enrolled["conv"]).get_json()

    # The reply is kept exactly as the model wrote it...
    assert body["response"] == "Star: Welcome back.\n**Sky:** Hi! I'm practising too."
    assert Message.query.get(body["message_id"]).content == body["response"]
    # ...and split for the page.
    assert [(p["speaker"]["name"], p["speaker"]["role"], p["text"]) for p in body["parts"]] == [
        ("Star", "Facilitator", "Welcome back."), ("Sky", "Practice student", "Hi! I'm practising too.")]
    assert body["parts"][0]["speaker"]["image_url"] == enrolled["face"].url
    # No picture: initials, two letters because Star and Sky share an S.
    assert (body["parts"][1]["speaker"]["image_url"], body["parts"][1]["speaker"]["initial"]) == (None, "Sk")

    # The model sees its own tagged reply in the history, so it keeps the format.
    assert send(c, enrolled["conv"], "again").status_code == 200
    assert any("Star: Welcome back." in (m.get("content") or "") for m in enrolled["histories"][-1])


def test_the_exercise_page_shows_each_part_under_its_speaker(enrolled, login_as):
    c = login_as(enrolled["patient"])
    send(c, enrolled["conv"])
    page = c.get(f"/exercise/{enrolled['conv'].id}").get_data(as_text=True)

    assert 'data-speaker="Star"' in page and 'data-speaker="Sky"' in page
    assert page.index('data-speaker="Star"') < page.index('data-speaker="Sky"')
    assert "Facilitator" in page and "Practice student" in page
    assert f'src="{enrolled["face"].url}"' in page
    # The waiting line names the main speaker.
    assert 'data-writer="Star"' in page


def test_a_chat_without_a_cast_shows_replies_as_before(enrolled, login_as):
    chat = enrolled["template"].flow_chat
    chat.speaker_ids, chat.main_speaker_id = None, None
    _db.session.commit()
    c = login_as(enrolled["patient"])

    body = send(c, enrolled["conv"]).get_json()
    page = c.get(f"/exercise/{enrolled['conv'].id}").get_data(as_text=True)

    assert "parts" not in body
    assert "data-speaker=" not in page and "data-writer" not in page
    assert "Star: Welcome back." in page


def test_a_speakers_picture_shows_only_if_the_participant_may_load_it(enrolled, login_as):
    # A picture from another researcher's library (it can't be chosen through
    # the API, but if it were there) is left out; the initial shows instead.
    other_face = image(enrolled["other"])
    enrolled["star"].picture_asset_id = other_face.id
    _db.session.commit()
    body = send(login_as(enrolled["patient"]), enrolled["conv"]).get_json()
    assert body["parts"][0]["speaker"]["image_url"] is None


# ── The notebook ───────────────────────────────────────────────

def save(client, conv, **extra):
    return client.post("/api/save_selection", json={"conversation_id": conv.id, "text": "Hi! I'm practising too.",
                                                    "message_ids": [], **extra})


def test_a_saved_line_keeps_who_said_it(enrolled, login_as):
    c = login_as(enrolled["patient"])
    send(c, enrolled["conv"])

    assert save(c, enrolled["conv"], speaker_name="sky").status_code == 200
    assert save(c, enrolled["conv"], speaker_name="Moon").status_code == 200       # not in the cast: dropped
    assert save(c, enrolled["conv"], speaker_name=["Sky"]).status_code == 400

    assert [s.speaker_name for s in SavedSelection.query.order_by(SavedSelection.id)] == ["Sky", None]
    assert c.get("/api/selections").get_json()[-1]["speaker_name"] == "Sky"
    notebook = c.get("/notebook").get_data(as_text=True)
    assert "Sky · " in notebook
    panel = c.get(f"/exercise/{enrolled['conv'].id}").get_data(as_text=True)
    assert "Sky · Meet Sky and Star" in panel
