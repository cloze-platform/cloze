"""The redesigned participant pages: who can open them, and the menu on them."""

import re

import pytest

from llm_chat.models import AdminSettings, ProviderFeatureFlags, SafetyPlan

PAGES = ["/help", "/exercises", "/notebook", "/safety-plan", "/reports"]


@pytest.fixture
def v2(db):
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()


def _approve_plan(db, study, **sections):
    plan = SafetyPlan(patient_id=study["patient"].id, status="active")
    for name, value in sections.items():
        getattr(plan, f"set_{name}")(value)
    db.session.add(plan)
    db.session.commit()
    return plan


def _html(client, path="/dashboard"):
    resp = client.get(path)
    assert resp.status_code == 200, path
    return resp.get_data(as_text=True)


def _rail(html):
    return html[html.index('<nav aria-label="Study"'):html.index("</nav>")]


# ── Who can open them ──

@pytest.mark.parametrize("path", PAGES)
def test_signed_out_goes_to_sign_in(client, v2, path):
    resp = client.get(path)
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize("role", ["provider", "admin"])
def test_researchers_and_admins_get_404(make_user, login_as, v2, path, role):
    assert login_as(make_user("u", role=role)).get(path).status_code == 404


@pytest.mark.parametrize("path", PAGES)
def test_pages_do_not_exist_on_v1(make_user, login_as, path):
    assert login_as(make_user("p")).get(path).status_code == 404


@pytest.mark.parametrize("path", PAGES)
def test_participants_on_v2_get_the_page(study, login_as, v2, path):
    html = _html(login_as(study["patient"]), path)
    assert '<nav aria-label="Study"' in html and '<nav aria-label="Main"' in html


# ── The menu ──

def test_menu_lists_the_participants_groups_and_exercises_only(study, login_as, v2):
    rail = _rail(_html(login_as(study["patient"])))
    for name in ["Week 1", "Week 2", "Intro", "Characters", "Pilot", "Thought records", "Sky", "Star"]:
        assert name in rail
    for hidden in ["Hidden window", "Secret", "Hidden chat", "Not yours", "Someone else"]:
        assert hidden not in rail


def test_menu_marks_the_current_page(study, login_as, v2, db):
    _approve_plan(db, study)
    client = login_as(study["patient"])
    for path, label in [("/dashboard", "Home"), ("/notebook", "Notebook"), ("/safety-plan", "Safety plan"),
                        ("/reports", "Reports")]:
        rail = _rail(_html(client, path))
        current = re.findall(r'aria-current="page"[^>]*>.*?</a>', rail, re.S)
        assert len(current) == 1 and label in current[0], path


def test_exercise_links_open_the_conversation_or_the_template(study, login_as, v2, db):
    _approve_plan(db, study)
    rail = _rail(_html(login_as(study["patient"])))
    assert f'href="/exercise/{study["thoughts_conv"].id}"' in rail
    assert f'href="/exercise/template/{study["sky"].id}"' in rail
    assert f'href="/exercise/{study["star_conv"].id}"' in rail   # created, nothing sent yet


def test_unapproved_safety_plan_locks_exercises_not_started(study, login_as, v2):
    rail = _rail(_html(login_as(study["patient"])))
    assert "Open once your safety plan is approved" in rail
    assert f'/exercise/template/{study["sky"].id}"' not in rail          # locked: no link
    assert f'/exercise/{study["thoughts_conv"].id}"' in rail             # started: still open


def test_upcoming_groups_say_when_they_open(study, login_as, v2):
    rail = _rail(_html(login_as(study["patient"])))
    assert "Opens 20 Jan" in rail      # NOW + 5 days, New York time


def test_safety_plan_badge_when_its_the_participants_turn(study, login_as, v2, db):
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="draft"))
    db.session.commit()
    rail = _rail(_html(login_as(study["patient"])))
    assert "To do" in rail


@pytest.mark.parametrize("flag, setting, label, path", [
    ("users_can_save_selections", None, "Notebook", "/notebook"),
    ("require_safety_plan", "require_safety_plan", "Safety plan", "/safety-plan"),
    ("enable_nlp_report", "enable_nlp_report", "Reports", "/reports"),
])
def test_switched_off_features_leave_the_menu_and_tabs(study, login_as, v2, db, flag, setting, label, path):
    assert f'href="{path}"' in _html(login_as(study["patient"]))
    if setting:
        db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, **{setting: False}))
    else:
        db.session.add(AdminSettings(setting_name=flag, setting_value="false"))
    db.session.commit()
    assert f'href="{path}"' not in _html(login_as(study["patient"]))


def test_menu_has_get_help_now_and_sign_out(study, login_as, v2):
    html = _html(login_as(study["patient"]))
    assert html.count('data-help-open') == 2          # rail and phone top bar
    assert '<dialog id="help-dialog"' in html and 'href="tel:988"' in html
    assert 'href="/logout"' in html
    assert "participant/help.js" in html


# ── Get help now ──

def test_help_page_has_the_crisis_lines(study, login_as, v2):
    html = _html(login_as(study["patient"]), "/help")
    for line in ['href="tel:988"', 'href="sms:741741?&amp;body=HOME"', 'href="tel:911"']:
        assert line in html
    assert '<dialog id="help-dialog"' not in html        # the page is the help
    assert "From your safety plan" not in html


def test_help_shows_the_care_team_and_coping_from_an_approved_plan(study, login_as, v2, db):
    _approve_plan(db, study,
                  care_team=[{"name": "Dr Rivera", "role": "Psychologist",
                              "contact_protocol": "Call the clinic", "after_hours": "Page on call"}],
                  coping_strategies=[{"strategy": "Walk", "patient_language": "Go for a walk round the block"}])
    html = _html(login_as(study["patient"]), "/help")
    assert "Dr Rivera" in html and "Psychologist" in html and "After hours: Page on call" in html
    assert "Go for a walk round the block" in html and 'href="/safety-plan"' in html


def test_help_ignores_a_plan_that_is_not_approved(study, login_as, v2, db):
    db.session.add(SafetyPlan(patient_id=study["patient"].id, status="pending_review",
                              care_team='[{"name": "Dr Pending"}]'))
    db.session.commit()
    assert "Dr Pending" not in _html(login_as(study["patient"]), "/help")


def test_care_team_text_is_escaped(study, login_as, v2, db):
    _approve_plan(db, study, care_team=[{"name": "<script>alert(1)</script>"}])
    html = _html(login_as(study["patient"]), "/help")
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ── Exercises page ──

def test_exercises_page_lists_groups_in_the_order_they_open(study, login_as, v2, db):
    _approve_plan(db, study)
    html = _html(login_as(study["patient"]), "/exercises")
    main = html[html.index('<main'):html.index('</main>')]
    order = [main.index(n) for n in ["Pilot", "Characters", "Intro", "Week 1", "Week 2"]]
    assert order == sorted(order)
    assert "1 started · 2 finished" in main
    assert "Continue" in main and "Start" in main and "Finished" in main


def test_a_participant_with_nothing_yet(make_user, login_as, v2):
    html = _html(login_as(make_user("new")), "/exercises")
    assert "Your exercises will appear here" in html


def test_home_opens_the_group_with_work_in_progress(study, login_as, v2, db):
    _approve_plan(db, study)
    rail = _rail(_html(login_as(study["patient"])))
    opened = re.findall(r"<details[^>]*\bopen\b[^>]*>\s*<summary.*?</summary>", rail, re.S)
    assert len(opened) == 1 and "Week 1" in opened[0]


def test_group_summaries_count_started_and_finished(study, login_as, v2, db):
    _approve_plan(db, study)
    main = _html(login_as(study["patient"]), "/exercises").split("<main", 1)[1]
    assert "1 started" in main and "All finished" in main and "2 exercises" in main and "Opens Wed 20 Jan" in main


# ── Home ──

def _main(html):
    return html[html.index("<main"):html.index("</main>")]


def _home(client):
    return _main(_html(client, "/dashboard"))


def test_home_shows_open_groups_and_whats_coming_up(study, login_as, v2, db):
    _approve_plan(db, study)
    home = _home(login_as(study["patient"]))
    assert "Welcome back" in home and "Finish your safety plan" not in home
    assert "Week 1" in home and "Characters" in home and "Thought records" in home
    assert "Pilot chat" not in home and "Welcome</" not in home            # closed groups stay in the menu
    upcoming = home[home.index("Coming up"):]
    assert "Week 2" in upcoming and "Opens Wed 20 Jan" in upcoming
    assert f'href="/exercise/template/{study["checkin"].id}"' in home


@pytest.mark.parametrize("statuses, heading, link", [
    ([], "Your care team is starting your safety plan", None),
    (["draft"], "Finish your safety plan", "Continue my safety plan"),
    (["pending_review"], "Your safety plan is with your care team", "See my safety plan"),
])
def test_home_leads_with_the_safety_plan_step(study, login_as, v2, db, statuses, heading, link):
    for status in statuses:
        db.session.add(SafetyPlan(patient_id=study["patient"].id, status=status))
    db.session.commit()
    home = _home(login_as(study["patient"]))
    assert f'<h1 id="step-heading"' in home and heading in home
    assert (link in home) if link else ("Continue my safety plan" not in home)
    assert "These open once your care team approves your safety plan." in home
    assert f'/exercise/template/{study["checkin"].id}"' not in home         # locked


def test_safety_plan_step_counts_the_participants_sections(study, login_as, v2, db):
    plan = SafetyPlan(patient_id=study["patient"].id, status="draft")
    plan.set_warning_signs([{"sign": "Not sleeping"}])
    plan.set_reasons_for_living([{"reason": "My dog"}])
    db.session.add(plan)
    db.session.commit()
    assert "2 of 4 sections" in _home(login_as(study["patient"]))


@pytest.mark.parametrize("statuses", [["active"], ["active", "pending_review"]])
def test_no_safety_plan_step_once_approved(study, login_as, v2, db, statuses):
    for status in statuses:
        db.session.add(SafetyPlan(patient_id=study["patient"].id, status=status))
    db.session.commit()
    assert "step-heading" not in _home(login_as(study["patient"]))


def test_no_safety_plan_step_when_the_study_has_none(study, login_as, v2, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, require_safety_plan=False))
    db.session.commit()
    home = _home(login_as(study["patient"]))
    assert "step-heading" not in home and f'/exercise/template/{study["checkin"].id}"' in home


def test_home_shows_closed_hours(study, login_as, v2, db, monkeypatch):
    _approve_plan(db, study)
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, access_hours_enabled=True,
                                        access_hours_start="09:00", access_hours_end="17:00"))
    db.session.commit()
    from llm_chat.utils import access_hours
    monkeypatch.setattr(access_hours, "within_access_window", lambda *a, **k: False)
    home = _home(login_as(study["patient"]))
    assert "Closed for now" in home and "Opens" in home and "You can still read your past chats." in home
    monkeypatch.setattr(access_hours, "within_access_window", lambda *a, **k: True)
    assert "Closed for now" not in _home(login_as(study["patient"]))


def test_home_notes_reports_ready_and_being_prepared(study, login_as, v2, db):
    from llm_chat.models import Report
    _approve_plan(db, study)
    home = _home(login_as(study["patient"]))
    assert "Your report from Intro is being prepared." in home              # ended, report not made yet
    assert "Your report is ready" not in home
    db.session.add(Report(window_id=study["pilot"].id, patient_id=study["patient"].id,
                          provider_id=study["provider"].id, report_type="summary", report_data="{}"))
    db.session.commit()
    assert "Your report is ready" in _home(login_as(study["patient"]))


def test_home_says_nothing_about_reports_when_they_are_off(study, login_as, v2, db):
    _approve_plan(db, study)
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, enable_nlp_report=False))
    db.session.commit()
    assert "being prepared" not in _home(login_as(study["patient"]))


def test_home_for_a_participant_with_nothing_yet(make_user, login_as, v2):
    home = _home(login_as(make_user("new")))
    assert "Nothing to do yet" in home and "data-help-open" in home
