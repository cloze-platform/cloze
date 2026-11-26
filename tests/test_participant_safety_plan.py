"""The Safety plan page: each state, what it shows, and the save-for-later flag."""

import json

import pytest

from llm_chat.models import AdminSettings, ProviderFeatureFlags, SafetyPlan


@pytest.fixture
def v2(db):
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()


def _plan(db, study, status, **sections):
    plan = SafetyPlan(patient_id=study["patient"].id, status=status, approved_at=1_799_000_000 if status == "active" else None)
    for name, value in sections.items():
        getattr(plan, f"set_{name}")(value)
    db.session.add(plan)
    db.session.commit()
    return plan


FULL = dict(warning_signs=[{"sign": "Not sleeping", "context": "Before exams", "severity": 4}],
            coping_strategies=[{"strategy": "Walking", "patient_language": "Reset walk", "effectiveness": 5}],
            support_network=[{"person": "Sam", "relationship": "Sister", "contact_preference": "Text", "comfort_level": 2}],
            reasons_for_living=[{"reason": "My dog"}])


def _main(client):
    html = client.get("/safety-plan").get_data(as_text=True)
    return html[html.index("<main"):html.index("</main>")]


def test_none_yet(study, login_as, v2):
    main = _main(login_as(study["patient"]))
    assert "Your care team is starting your plan" in main and 'id="plan-form"' not in main


def test_off(study, login_as, v2, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, require_safety_plan=False))
    db.session.commit()
    assert "Your study doesn't use a safety plan." in _main(login_as(study["patient"]))


def test_your_turn_shows_the_form_with_the_draft(study, login_as, v2, db):
    _plan(db, study, "draft", warning_signs=FULL["warning_signs"], reasons_for_living=FULL["reasons_for_living"],
          care_team=[{"name": "Dr Rivera", "role": "Psychologist"}])
    main = _main(login_as(study["patient"]))
    assert "Your turn" in main and "2 of 4 parts added" in main
    assert 'id="plan-form" class=" flex' in main and 'data-draft="true"' in main
    assert 'value="Not sleeping"' in main and 'value="Before exams"' in main
    assert '<option value="4" selected>Moderate to severe</option>' in main
    assert "Save for later" in main and "Dr Rivera" in main
    assert "participant/safety-plan.js" in client_html(login_as(study["patient"]))


def client_html(client):
    return client.get("/safety-plan").get_data(as_text=True)


def test_waiting_shows_what_was_sent(study, login_as, v2, db):
    _plan(db, study, "pending_review", **FULL)
    main = _main(login_as(study["patient"]))
    assert "Waiting for your care team" in main and "Sent to your care team" in main
    assert "Reset walk: Walking" in main and 'id="plan-form"' not in main


def test_approved_reads_with_a_hidden_form_to_suggest_a_change(study, login_as, v2, db):
    _plan(db, study, "active", **FULL)
    main = _main(login_as(study["patient"]))
    assert "Approved" in main and "Suggest a change" in main and 'id="plan-view"' in main
    assert 'id="plan-form" class="hidden' in main and 'data-draft="false"' in main
    assert "Save for later" not in main and "Sam · Sister" in main


def test_change_waiting_reads_the_approved_plan_and_edits_the_suggestion(study, login_as, v2, db):
    _plan(db, study, "active", **FULL)
    _plan(db, study, "pending_review", **{**FULL, "reasons_for_living": [{"reason": "My garden"}]})
    main = _main(login_as(study["patient"]))
    view = main[main.index('id="plan-view"'):main.index('id="plan-form"')]
    form = main[main.index('id="plan-form"'):]
    assert "My dog" in view and "My garden" not in view
    assert 'value="My garden"' in form and "Change my suggestions" in main


def test_hidden_items_never_reach_the_page_and_text_is_escaped(study, login_as, v2, db):
    _plan(db, study, "active", **{**FULL, "warning_signs": [{"sign": "<script>alert(1)</script>"}]},
          anti_patterns=[{"pattern": "Team-only note", "visible_to_patient": False},
                         {"pattern": "Don't mention exams", "source": "provider"},
                         {"pattern": "No pep talks", "source": "patient", "visible_to_patient": True}],
          emergency_plan={"activation_conditions": "If you can't stay safe", "preferred_facility": "City ER",
                          "contraindications": "Clinical note"})
    main = _main(login_as(study["patient"]))
    assert "Team-only note" not in main and "Clinical note" not in main
    assert "<script>alert(1)" not in main and "&lt;script&gt;" in main
    assert "Don&#39;t mention exams" in main and "If you can&#39;t stay safe" in main and "City ER" in main
    assert "No pep talks" in main


def test_things_to_avoid_already_added_are_listed_not_editable(study, login_as, v2, db):
    _plan(db, study, "draft", anti_patterns=[{"pattern": "No pep talks", "source": "patient", "visible_to_patient": True}])
    main = _main(login_as(study["patient"]))
    form = main[main.index('id="plan-form"'):]
    assert "No pep talks" in form and 'value="No pep talks"' not in form
    assert "+ Add something to avoid" in form


def test_adding_things_to_avoid_can_be_switched_off(study, login_as, v2, db):
    db.session.add(ProviderFeatureFlags(provider_id=study["provider"].id, allow_patient_anti_patterns=False))
    _plan(db, study, "draft")
    assert "+ Add something to avoid" not in _main(login_as(study["patient"]))


# ── Save for later ──

def test_save_for_later_keeps_a_complete_draft(study, login_as, db):
    plan = _plan(db, study, "draft")
    resp = login_as(study["patient"]).put("/api/safety-plan/patient-sections", json={**FULL, "submit": False})
    assert resp.status_code == 200 and resp.get_json()["status"] == "draft"
    assert db.session.get(SafetyPlan, plan.id).is_complete()


def test_sending_a_complete_draft_moves_it_to_review(study, login_as, db):
    _plan(db, study, "draft")
    resp = login_as(study["patient"]).put("/api/safety-plan/patient-sections", json={**FULL, "submit": True})
    assert resp.get_json()["status"] == "pending_review"


def test_todays_page_sends_as_before(study, login_as, db):
    _plan(db, study, "draft")
    resp = login_as(study["patient"]).put("/api/safety-plan/patient-sections", json=FULL)
    assert resp.get_json()["status"] == "pending_review"


# ── What the plan accepts ──

@pytest.mark.parametrize("body", [
    {"warning_signs": 1},
    {"coping_strategies": ["walk"]},
    {"support_network": [{"person": "Sam", "comfort_level": 9}]},
    {"support_network": [{"person": "Sam", "comfort_level": True}]},
    {"reasons_for_living": [{"reason": "x" * 501}]},
    {"warning_signs": [{"sign": "x"}] * 51},
    {"warning_signs": [{"sign": ["not", "text"]}]},
])
def test_bad_sections_are_refused(study, login_as, db, body):
    _plan(db, study, "draft")
    resp = login_as(study["patient"]).put("/api/safety-plan/patient-sections", json=body)
    assert resp.status_code == 400


def test_sections_are_cleaned(study, login_as, db):
    plan = _plan(db, study, "draft")
    resp = login_as(study["patient"]).put("/api/safety-plan/patient-sections", json={
        "warning_signs": [{"sign": "  Not sleeping ", "extra": "<b>dropped</b>"}, {"sign": ""}],
        "submit": False})
    assert resp.status_code == 200
    assert db.session.get(SafetyPlan, plan.id).get_warning_signs() == [
        {"sign": "Not sleeping", "context": "", "severity": 3}]


@pytest.mark.parametrize("body", [{"pattern": ""}, {"pattern": 5}, {"pattern": "x" * 501}, {"pattern": "ok", "reason": 7}])
def test_bad_things_to_avoid_are_refused(study, login_as, db, body):
    _plan(db, study, "draft")
    assert login_as(study["patient"]).post("/api/safety-plan/anti-pattern", json=body).status_code == 400
