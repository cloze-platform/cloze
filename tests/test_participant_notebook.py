"""The Notebook page, and the participant's own note on a saved line."""

import pytest

from llm_chat.models import AdminSettings, SavedSelection


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


def _main(client, url="/notebook"):
    html = client.get(url).get_data(as_text=True)
    return html[html.index("<main"):html.index("</main>")]


# ── The contents ──

def test_contents_says_the_rule_and_lists_pages_in_menu_order(study, login_as, v2, lines):
    main = _main(login_as(study["patient"]))
    assert "Each exercise has its own page. What you save in an exercise goes on its page." in main
    assert "Your study team can read your notebook." in main
    # The same order as the Exercises menu: Intro opened before Week 1.
    assert main.index(">Intro</h2>") < main.index(">Week 1</h2>")
    assert main.index("Welcome") < main.index("Thought records")
    thoughts = f'href="/notebook/page/{study["thoughts_conv"].id}"'
    assert thoughts in main and "2 lines · 1 thought" in main
    # Each card previews its latest line, escaped.
    card = main[main.index(thoughts):]
    assert "&lt;b&gt;bold&lt;/b&gt; claim" in card[:card.index("</a>")]
    assert "Someone else" not in main


def test_the_old_pretend_button_is_gone(study, login_as, v2, lines):
    main = _main(login_as(study["patient"]))
    assert "Save to notebook</span>" not in main and ">Add a note<" not in main


def test_search_data_covers_every_entry_and_stays_inert(study, login_as, v2, lines):
    html = login_as(study["patient"]).get("/notebook").get_data(as_text=True)
    data = html[html.index('id="notebook-data">'):]
    data = data[:data.index("</script>")]
    assert "\\u003cb\\u003ebold" in data             # tojson escapes < and >, so it can't end the script
    assert "Remember this" in data and "Welcome line" in data and "Someone else" not in data


# ── A page ──

def test_a_page_in_chat_order_with_thoughts_and_back_to_the_moment(study, login_as, v2, lines, db):
    from llm_chat.models import Message
    conv = study["thoughts_conv"]
    first_user, first_reply = (Message.query.filter_by(conversation_id=conv.id).order_by(Message.id).limit(2).all())
    lines[0].message_ids = f"[{first_reply.id}]"     # "Thoughts shape feelings": the model's line
    lines[1].message_ids = f"[{first_user.id}]"      # "<b>bold</b> claim": the participant's own words
    db.session.commit()
    main = _main(login_as(study["patient"]), f"/notebook/page/{conv.id}")

    assert main.index("&lt;b&gt;bold&lt;/b&gt; claim") < main.index("Thoughts shape feelings")   # chat order
    assert '<span class="font-semibold text-p-ink-2">You</span>' in main
    assert f'href="/exercise/{conv.id}#m-{first_reply.id}"' in main
    assert ">Remember this</textarea>" in main and 'placeholder="Write a thought…"' in main
    assert "Remove from notebook" in main
    # Intro (Welcome) comes before Week 1 in the menu, so it's the previous page.
    assert "Previous page" in main and "Welcome" in main and "Next page" not in main


def test_pages_that_dont_exist_are_404(study, login_as, v2, lines):
    client = login_as(study["patient"])
    assert client.get(f"/notebook/page/{study['star_conv'].id}").status_code == 404      # nothing saved there
    assert client.get("/notebook/page/999999").status_code == 404
    assert login_as(study["other"]).get(f"/notebook/page/{study['thoughts_conv'].id}").status_code == 404


def test_the_chat_has_anchors_for_back_to_the_moment(study, login_as, v2, db):
    from llm_chat.models import Message
    conv = study["thoughts_conv"]
    conv.consent_provided = True
    db.session.commit()
    html = login_as(study["patient"]).get(f"/exercise/{conv.id}").get_data(as_text=True)
    for m in Message.query.filter_by(conversation_id=conv.id):
        assert f'id="m-{m.id}"' in html


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
    assert login_as(study["patient"]).get(f"/notebook/page/{study['thoughts_conv'].id}").status_code == 404


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
