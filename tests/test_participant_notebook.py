"""The Notebook page, and the participant's own note on a saved line."""

import pytest

from llm_chat.models import AdminSettings, SavedSelection


@pytest.fixture
def v2(db):
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()


@pytest.fixture
def lines(study, db):
    made = [
        SavedSelection(user_id=study["patient"].id, conversation_id=study["thoughts_conv"].id,
                       selection_text="Thoughts shape feelings", note="Remember this", created_at=1_799_990_000),
        SavedSelection(user_id=study["patient"].id, conversation_id=study["thoughts_conv"].id,
                       selection_text="<b>bold</b> claim", created_at=1_799_999_000),
        SavedSelection(user_id=study["patient"].id, conversation_id=study["welcome_conv"].id,
                       selection_text="Welcome line", created_at=1_799_000_000),
        SavedSelection(user_id=study["other"].id, conversation_id=study["thoughts_conv"].id,
                       selection_text="Someone else's line"),
    ]
    db.session.add_all(made)
    db.session.commit()
    return made


def _main(client):
    html = client.get("/notebook").get_data(as_text=True)
    return html[html.index("<main"):html.index("</main>")]


def test_lines_grouped_by_exercise_newest_first(study, login_as, v2, lines):
    main = _main(login_as(study["patient"]))
    assert main.index("Thought records") < main.index("Welcome")
    assert "Week 1 · 2 saved" in main and "Intro · 1 saved" in main
    assert f'href="/exercise/{study["thoughts_conv"].id}"' in main
    assert main.index("&lt;b&gt;bold&lt;/b&gt; claim") < main.index("Thoughts shape feelings")
    assert "Someone else" not in main
    assert "Your study team can see them too." in main


def test_the_participants_note_is_shown_apart(study, login_as, v2, lines):
    main = _main(login_as(study["patient"]))
    assert '<span data-note-text>Remember this</span>' in main
    assert main.count(">Edit note<") == 1 and main.count(">Add a note<") == 2


def test_empty_notebook(study, login_as, v2, db):
    from llm_chat.models import SafetyPlan
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="active"))
    db.session.commit()
    main = _main(login_as(study["patient"]))
    assert "Nothing saved yet" in main and "Go to Thought records" in main      # the exercise in progress


def test_404_when_saving_is_off(study, login_as, v2, db):
    db.session.add(AdminSettings(setting_name="users_can_save_selections", setting_value="false"))
    db.session.commit()
    assert login_as(study["patient"]).get("/notebook").status_code == 404


# ── The selections API ──

def test_selections_api_gives_note_and_title_separately(study, login_as, lines):
    data = {s["text"]: s for s in login_as(study["patient"]).get("/api/selections").get_json()}
    noted, bare = data["Thoughts shape feelings"], data["<b>bold</b> claim"]
    assert (noted["own_note"], noted["conversation_title"], noted["note"]) == ("Remember this", "Thought records", "Remember this")
    assert (bare["own_note"], bare["conversation_title"], bare["note"]) == (None, "Thought records", "Thought records")


def test_participants_edit_and_clear_their_own_notes(study, login_as, lines, db):
    client, line = login_as(study["patient"]), lines[1]
    resp = client.put(f"/api/selections/{line.id}", json={"note": "  My take  "})
    assert resp.status_code == 200 and resp.get_json()["own_note"] == "My take"
    assert client.put(f"/api/selections/{line.id}", json={"note": ""}).get_json()["own_note"] is None
    assert db.session.get(SavedSelection, line.id).note is None


def test_nobody_else_can_change_a_note(study, login_as, lines, make_user):
    line = lines[0]
    assert login_as(study["other"]).put(f"/api/selections/{line.id}", json={"note": "x"}).status_code == 403
    assert login_as(study["provider"]).put(f"/api/selections/{line.id}", json={"note": "x"}).status_code == 403


@pytest.mark.parametrize("note", ["x" * 1001, 42])
def test_notes_are_checked(study, login_as, lines, note):
    assert login_as(study["patient"]).put(f"/api/selections/{lines[0].id}", json={"note": note}).status_code == 400
