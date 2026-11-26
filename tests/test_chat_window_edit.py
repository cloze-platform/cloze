"""Editing a chat window (PUT /api/windows/<id>) after participants have
started chatting in it.

Conversations point at their chat template (conversations.template_id), and
participant_nav matches a conversation to its exercise by (window, template).
So an edit has to keep the templates it is given, not recreate them. Run these
against Postgres too: SQLite doesn't enforce the foreign key.
"""

from conftest import DAY

from llm_chat.extensions import db as _db
from llm_chat.models import ChatTemplate, Conversation, ProviderFeatureFlags
from llm_chat.services import participant_nav


def _edit_payload(client, window_id):
    """What the edit form sends: the window as loaded, sent back."""
    w = client.get(f"/api/windows/{window_id}").get_json()
    return {
        "title": w["title"], "description": w["description"],
        "start_date": w["start_date"], "end_date": w["end_date"],
        "report_config": w["report_config"],
        "templates": [{k: t[k] for k in ("id", "title", "purpose", "model_id",
                                         "system_prompt_id", "custom_system_prompt")}
                      for t in w["templates"]],
    }


def _exercises(patient, window):
    group = next(g for g in participant_nav.build(patient).groups if g.window.id == window.id)
    return [(e.template.title, e.conversation is not None) for e in group.exercises]


def _template(template_id):
    _db.session.expire_all()
    return _db.session.get(ChatTemplate, template_id)


def test_extending_a_started_window_keeps_its_exercises(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    payload = _edit_payload(client, week1.id)
    payload["end_date"] += 7 * DAY

    resp = client.put(f"/api/windows/{week1.id}", json=payload)

    assert resp.status_code == 200
    assert _template(study["thoughts"].id).window_id == week1.id
    assert _db.session.get(Conversation, study["thoughts_conv"].id).template_id == study["thoughts"].id
    assert _exercises(study["patient"], week1) == [("Thought records", True), ("Check-in", False)]


def test_edit_form_loads_only_visible_templates(study, login_as):
    payload = _edit_payload(login_as(study["provider"]), study["week1"].id)
    assert [t["title"] for t in payload["templates"]] == ["Thought records", "Check-in"]


def test_templates_are_updated_in_place_in_the_order_sent(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    thoughts, checkin = study["thoughts"].id, study["checkin"].id
    _template(thoughts).max_messages = 20
    _db.session.commit()
    payload = _edit_payload(client, week1.id)
    payload["templates"].reverse()
    payload["templates"][0]["title"] = "Daily check-in"

    assert client.put(f"/api/windows/{week1.id}", json=payload).status_code == 200

    assert (_template(checkin).title, _template(checkin).order_index) == ("Daily check-in", 0)
    assert _template(thoughts).order_index == 1
    assert _template(thoughts).max_messages == 20  # the form doesn't send it
    assert _exercises(study["patient"], week1) == [("Daily check-in", False), ("Thought records", True)]


def test_new_templates_are_added(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    payload = _edit_payload(client, week1.id)
    payload["templates"].append({"id": None, "title": "Wrap-up", "purpose": "End of week",
                                 "model_id": study["model"].id, "system_prompt_id": None,
                                 "custom_system_prompt": None})

    assert client.put(f"/api/windows/{week1.id}", json=payload).status_code == 200

    added = ChatTemplate.query.filter_by(window_id=week1.id, title="Wrap-up").one()
    assert (added.order_index, added.visible) == (2, True)
    assert _exercises(study["patient"], week1) == [("Thought records", True), ("Check-in", False),
                                                    ("Wrap-up", False)]


def test_removed_templates_are_hidden_if_started_and_deleted_if_not(study, login_as):
    client = login_as(study["provider"])
    characters = study["characters"]
    payload = _edit_payload(client, characters.id)
    payload["templates"] = []

    assert client.put(f"/api/windows/{characters.id}", json=payload).status_code == 200

    assert _template(study["sky"].id) is None
    assert _template(study["star"].id).visible is False
    assert _db.session.get(Conversation, study["star_conv"].id).template_id == study["star"].id
    assert _exercises(study["patient"], characters) == []


def test_hidden_templates_are_left_alone(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    hidden = ChatTemplate.query.filter_by(window_id=week1.id, title="Hidden chat").one().id

    assert client.put(f"/api/windows/{week1.id}", json=_edit_payload(client, week1.id)).status_code == 200

    assert _template(hidden).visible is False


def test_templates_from_another_window_are_refused(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    payload = _edit_payload(client, week1.id)
    payload["title"] = "Renamed"
    payload["templates"].append({"id": study["activation"].id, "title": "Taken over",
                                 "model_id": study["model"].id})

    assert client.put(f"/api/windows/{week1.id}", json=payload).status_code == 400

    assert _template(study["activation"].id).title == "Behavioural activation"
    assert _template(study["checkin"].id).window.title == "Week 1"


def test_a_model_outside_the_allowlist_changes_nothing(study, login_as):
    client = login_as(study["provider"])
    week1 = study["week1"]
    _db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id,
                                         allowed_models=f"[{study['model'].id}]"))
    _db.session.commit()
    payload = _edit_payload(client, week1.id)
    payload["templates"] = [dict(payload["templates"][1], model_id=study["model"].id + 1)]

    assert client.put(f"/api/windows/{week1.id}", json=payload).status_code == 403

    assert _template(study["thoughts"].id).visible is True
    assert _exercises(study["patient"], week1) == [("Thought records", True), ("Check-in", False)]
