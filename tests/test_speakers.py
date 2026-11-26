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
