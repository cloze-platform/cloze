"""The participant_ui switch: which participant interface /dashboard serves."""

import pytest

from llm_chat.models import AdminSettings
from llm_chat.utils.participant_ui import participant_ui

OLD = 'id="homeView"'        # today's single-page dashboard
NEW = 'id="announcer"'       # the participant shell (templates/participant/base.html)


def _set(db, value):
    row = AdminSettings.query.filter_by(setting_name="participant_ui").first()
    if row is None:
        row = AdminSettings(setting_name="participant_ui")
        db.session.add(row)
    row.setting_value = value
    db.session.commit()


def test_without_the_setting_participants_get_todays_page(make_user, login_as):
    body = login_as(make_user("p1")).get("/dashboard").get_data(as_text=True)
    assert OLD in body and NEW not in body
    assert participant_ui() == "v1"


def test_v2_serves_the_new_participant_home(db, make_user, login_as):
    _set(db, "v2")
    res = login_as(make_user("p1")).get("/dashboard")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert NEW in body and OLD not in body
    assert "--p-page" in body


@pytest.mark.parametrize("value", ["v1", "v3", "", None, "true"])
def test_anything_but_v2_keeps_todays_page(db, make_user, login_as, value):
    _set(db, value)
    assert participant_ui() == "v1"
    body = login_as(make_user("p1")).get("/dashboard").get_data(as_text=True)
    assert OLD in body


@pytest.mark.parametrize("value", ['"v2"', " V2 "])
def test_v2_tolerates_json_quoting_and_case(db, value):
    _set(db, value)
    assert participant_ui() == "v2"


def test_admin_settings_api_turns_it_on_and_back_off(make_user, login_as):
    admin, patient = make_user("admin1", role="admin"), make_user("p1")
    # A fresh client per identity: Flask-Login caches the user per app context.
    assert login_as(admin).post("/api/admin/settings", json={"participant_ui": "v2"}).status_code == 200
    assert NEW in login_as(patient).get("/dashboard").get_data(as_text=True)

    assert login_as(admin).post("/api/admin/settings", json={"participant_ui": "v1"}).status_code == 200
    assert OLD in login_as(patient).get("/dashboard").get_data(as_text=True)


@pytest.mark.parametrize("role, template_marker", [
    ("provider", "provider_dashboard"),
    ("admin", "admin_dashboard"),
])
def test_researchers_and_admins_are_unaffected(db, make_user, login_as, monkeypatch, role, template_marker):
    _set(db, "v2")
    rendered = []
    import llm_chat.routes.conversations as conv
    monkeypatch.setattr(conv, "render_template", lambda name, **kw: rendered.append(name) or "")
    login_as(make_user("u1", role=role)).get("/dashboard")
    assert rendered == [f"{template_marker}.html"]
