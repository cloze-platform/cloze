"""The exercise page: who can open it, and each state it can be in."""

import pytest

from llm_chat.models import AdminSettings, Conversation, Message, ProviderFeatureFlags, SafetyPlan
from llm_chat.services.conversation_end import end


@pytest.fixture
def approved(db, study):
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="active"))
    db.session.commit()


def _agreed(db, *conversations):
    for c in conversations:
        c.consent_provided = True
    db.session.commit()


def _page(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    html = resp.get_data(as_text=True)
    return html[html.index("<main"):html.index("</main>")]


def _url(conv):
    return f"/exercise/{conv.id}"


# ── Who can open it ──

def test_signed_out_goes_to_sign_in(client, v2, study):
    resp = client.get(_url(study["thoughts_conv"]))
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


@pytest.mark.parametrize("role", ["provider", "admin"])
def test_researchers_and_admins_get_404(study, login_as, make_user, v2, role):
    assert login_as(make_user("u", role=role)).get(_url(study["thoughts_conv"])).status_code == 404


def test_404_on_v1(study, login_as):
    assert login_as(study["patient"]).get(_url(study["thoughts_conv"])).status_code == 404


def test_another_participants_conversation_is_404(study, login_as, v2):
    other = Conversation.query.filter_by(title="Not yours").one()
    assert login_as(study["patient"]).get(_url(other)).status_code == 404
    assert login_as(study["other"]).get(_url(study["thoughts_conv"])).status_code == 404
    assert login_as(study["other"]).get(f"/exercise/template/{study['checkin'].id}").status_code == 404


def test_hidden_windows_and_windowless_chats_are_404(study, login_as, v2):
    client = login_as(study["patient"])
    for title in ("Secret", "Old free chat"):
        assert client.get(_url(Conversation.query.filter_by(title=title).one())).status_code == 404


def test_a_started_template_redirects_to_its_conversation(study, login_as, v2):
    resp = login_as(study["patient"]).get(f"/exercise/template/{study['star'].id}")
    assert resp.status_code == 302 and resp.headers["Location"].endswith(_url(study["star_conv"]))


# ── Before you start ──

def test_not_started_shows_the_safety_information_first(study, login_as, v2, approved):
    main = _page(login_as(study["patient"]), f"/exercise/template/{study['checkin'].id}")
    assert "Important safety information" in main and "Required reporting" in main
    assert f'data-template-id="{study["checkin"].id}"' in main and "data-conversation-id" not in main
    assert "I understand this information" in main


def test_a_conversation_not_yet_agreed_shows_it_too(study, login_as, v2):
    main = _page(login_as(study["patient"]), _url(study["star_conv"]))
    assert "Important safety information" in main
    assert f'data-conversation-id="{study["star_conv"].id}"' in main


def test_team_written_blocks_are_escaped_with_bold(study, login_as, v2, db):
    import json
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, safety_disclaimer_text=json.dumps([
        {"type": "text", "content": "Read **this** <b>first</b>"},
        {"type": "warning", "title": "Crisis", "content": "If needed:\n- Call **988**\n- Call 911"},
        {"type": "alert", "title": "Reporting", "content": "We may tell your team."},
        {"type": "checkbox", "content": "I **agree** to the study rules"},
    ])))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["star_conv"]))
    assert "Read <strong>this</strong> &lt;b&gt;first&lt;/b&gt;" in main
    assert "<li>Call <strong>988</strong></li>" in main and "We may tell your team." in main
    assert "I <strong>agree</strong> to the study rules" in main
    assert "Required reporting" not in main                      # the built-in text is replaced


def test_raw_html_is_never_put_on_the_page_unsanitised(study, login_as, v2, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id,
                                        safety_disclaimer_text='<p>Ours</p><img src=x onerror="alert(1)">'))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["star_conv"]))
    assert 'data-custom-html="&lt;p&gt;Ours&lt;/p&gt;&lt;img src=x onerror=&#34;alert(1)&#34;&gt;"' in main
    assert "<img src=x" not in main and "Required reporting" in main   # built-in text until cleaned


# ── Open ──

def test_open_exercise_shows_the_conversation(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert "Important safety information" not in main
    assert main.count("data-message-id") == 4 and main.count("data-md") == 2
    assert "Thought records" in main and "Week 1" in main
    assert "Open until" in main and "This AI tool does not provide therapy" in main


def test_message_content_is_escaped(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    for role, text in (("user", "<script>alert(1)</script>"), ("assistant", '<img src=x onerror="alert(2)">')):
        db.session.add(Message(conversation_id=study["thoughts_conv"].id, role=role, content=text, timestamp=1))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert "<script>alert(1)" not in main and "&lt;script&gt;alert(1)" in main
    assert "<img src=x" not in main


def test_an_empty_agreed_chat_shows_the_greeting(study, login_as, v2, db):
    _agreed(db, study["star_conv"])
    main = _page(login_as(study["patient"]), _url(study["star_conv"]))
    assert 'id="greeting"' in main and "Send a message to get started." in main


def test_turns_left_and_the_few_turns_notice(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=6))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert "4 turns left" in main and "4 turns left in this exercise." in main
    assert 'id="few-turns" class="flex' in main


def test_no_few_turns_notice_with_plenty_left(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=40))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert "38 turns left" in main and 'id="few-turns" class="hidden' in main


# ── Finished and not open ──

def test_finished_by_the_turn_limit(study, login_as, v2, db, approved):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, max_turns_per_conversation=2))
    _agreed(db, study["thoughts_conv"])
    end(study["thoughts_conv"], Conversation.TURN_LIMIT)
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert "That's all 2 turns for this exercise" in main
    assert f'href="/exercise/template/{study["checkin"].id}"' in main and "Next: Check-in" in main
    assert "turns left" not in main and "This AI tool" not in main


def test_finished_when_the_window_closed(study, login_as, v2):
    main = _page(login_as(study["patient"]), _url(study["welcome_conv"]))
    assert "This exercise closed on Tuesday, 12 January" in main      # NOW - 3 days, New York time
    assert "Everything you wrote is still here to read." in main
    assert main.count("data-message-id") == 2


def test_not_open_yet(study, login_as, v2, approved):
    main = _page(login_as(study["patient"]), f"/exercise/template/{study['activation'].id}")
    assert "Opens Wednesday, 20 January" in main and "Important safety information" not in main


def test_closed_before_it_was_started(study, login_as, v2, approved):
    template = study["intro"].templates.filter_by(title="Never started").one()
    main = _page(login_as(study["patient"]), f"/exercise/template/{template.id}")
    assert "This exercise closed on" in main and "Everything you wrote" not in main


def test_locked_until_the_safety_plan_is_approved(study, login_as, v2):
    main = _page(login_as(study["patient"]), f"/exercise/template/{study['checkin'].id}")
    assert "This exercise opens once your safety plan is approved" in main
    assert 'href="/safety-plan"' in main and "Important safety information" not in main


# ── Layout ──

def test_the_menu_marks_the_exercise_and_the_phone_gets_its_own_header(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    html = login_as(study["patient"]).get(_url(study["thoughts_conv"])).get_data(as_text=True)
    rail = html[html.index('<nav aria-label="Study"'):html.index("</nav>")]
    assert f'href="{_url(study["thoughts_conv"])}" aria-current="page"' in rail
    assert '<nav aria-label="Main"' not in html                # no phone tabs
    assert "Back to Home" in html and html.count("data-help-open") >= 2


def test_the_reply_box_only_when_replying_is_possible(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"], study["welcome_conv"])
    client = login_as(study["patient"])
    html = client.get(_url(study["thoughts_conv"])).get_data(as_text=True)
    assert f'<form id="composer" data-conversation-id="{study["thoughts_conv"].id}"' in html
    assert 'id="reply"' in html and "participant/chat.js" in html
    finished = client.get(_url(study["welcome_conv"])).get_data(as_text=True)
    assert 'id="composer"' not in finished and "participant/chat.js" not in finished
    agree = client.get(_url(study["star_conv"])).get_data(as_text=True)
    assert 'id="composer"' not in agree


# ── Side panel: the Notebook ──

def test_the_notebook_panel_lists_saved_lines_escaped(study, login_as, v2, db):
    from llm_chat.models import SavedSelection
    _agreed(db, study["thoughts_conv"])
    db.session.add_all([
        SavedSelection(user_id=study["patient"].id, conversation_id=study["thoughts_conv"].id,
                       selection_text="<b>a line</b> I liked", created_at=1_800_000_000 - 120),
        SavedSelection(user_id=study["other"].id, conversation_id=study["thoughts_conv"].id,
                       selection_text="someone else's line"),
    ])
    db.session.commit()
    html = login_as(study["patient"]).get(_url(study["thoughts_conv"])).get_data(as_text=True)
    panel = html[html.index('<aside id="panel"'):html.index("</aside>")]
    assert "&lt;b&gt;a line&lt;/b&gt; I liked" in panel and "someone else" not in panel
    assert "Thought records · 2 min ago" in panel
    assert 'id="panel-toggle"' in html and 'data-notebook-count>1<' in html
    assert f'data-save-to="{study["thoughts_conv"].id}"' in html
    assert "participant/panel.js" in html and "participant/select-save.js" in html


def test_no_notebook_when_saving_is_off(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    db.session.add(AdminSettings(setting_name="users_can_save_selections", setting_value="false"))
    db.session.commit()
    html = login_as(study["patient"]).get(_url(study["thoughts_conv"])).get_data(as_text=True)
    assert '<aside id="panel"' not in html and "panel-toggle" not in html and "data-save-to" not in html
    assert "select-save.js" not in html


def test_nothing_to_save_from_before_a_conversation_exists(study, login_as, v2, approved):
    html = login_as(study["patient"]).get(f"/exercise/template/{study['checkin'].id}").get_data(as_text=True)
    assert '<aside id="panel"' in html and "data-save-to" not in html


def test_a_message_whose_reply_failed_offers_try_again(study, login_as, v2, db):
    _agreed(db, study["thoughts_conv"])
    db.session.add(Message(conversation_id=study["thoughts_conv"].id, role="user", content="Still here?",
                           timestamp=1_800_000_001, client_message_id="saved-without-reply"))
    db.session.commit()
    main = _page(login_as(study["patient"]), _url(study["thoughts_conv"]))
    assert 'data-client-id="saved-without-reply" data-pending-reply' in main
    assert "Saved. The reply didn't come through." in main and "data-retry" in main
