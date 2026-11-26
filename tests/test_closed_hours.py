"""Closed hours on the new participant pages: lock (the resting screen) or read-only."""

import pytest

from llm_chat.models import AdminSettings, ProviderFeatureFlags, SafetyPlan


@pytest.fixture
def hours(study, db, monkeypatch):
    """Opening hours on, and closed right now. Returns a setter for the mode."""
    flags = ProviderFeatureFlags(provider_id=study["provider"].id, access_hours_enabled=True,
                                 access_hours_start="09:00", access_hours_end="17:00")
    db.session.add_all([flags, SafetyPlan(patient_id=study["patient"].id, status="active")])
    study["thoughts_conv"].consent_provided = True
    db.session.commit()
    from llm_chat.utils import access_hours
    monkeypatch.setattr(access_hours, "within_access_window", lambda *a, **k: False)

    def set_mode(mode):
        flags.access_hours_mode = mode
        db.session.commit()
    return set_mode


def _get(client, path):
    return client.get(path)


# ── The setting ──

def test_researchers_choose_the_mode(study, login_as, db):
    client = login_as(study["provider"])
    assert client.get("/api/provider/my-flags").get_json()["access_hours_mode"] == "lock"
    assert client.put("/api/provider/my-flags", json={"access_hours_mode": "read_only"}).status_code == 200
    assert client.get("/api/provider/my-flags").get_json()["access_hours_mode"] == "read_only"
    assert client.put("/api/provider/my-flags", json={"access_hours_mode": "open"}).status_code == 400


def test_the_settings_page_offers_it_only_on_v2(study, login_as, db):
    assert 'id="accessHoursMode"' not in login_as(study["provider"]).get("/provider/settings").get_data(as_text=True)
    db.session.add(AdminSettings(setting_name="participant_ui", setting_value="v2"))
    db.session.commit()
    assert 'id="accessHoursMode"' in login_as(study["provider"]).get("/provider/settings").get_data(as_text=True)


def test_the_access_window_api_reports_the_mode(study, login_as, hours):
    hours("read_only")
    data = login_as(study["patient"]).get("/api/access-window").get_json()
    assert data["enabled"] is True and data["open"] is False and data["mode"] == "read_only"
    assert data["reopen"].startswith("Opens") and data["reopens_at"]


# ── Lock: the resting screen stands in for the site ──

@pytest.mark.parametrize("path", ["/dashboard", "/exercises", "/notebook", "/reports", "EXERCISE"])
def test_lock_sends_everything_to_the_resting_screen(study, login_as, v2, hours, path):
    path = f"/exercise/{study['thoughts_conv'].id}" if path == "EXERCISE" else path
    resp = login_as(study["patient"]).get(path)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/closed")


@pytest.mark.parametrize("path", ["/help", "/safety-plan"])
def test_lock_keeps_help_and_the_safety_plan_open(study, login_as, v2, hours, path):
    assert login_as(study["patient"]).get(path).status_code == 200


def test_the_resting_screen(study, login_as, v2, hours):
    html = login_as(study["patient"]).get("/closed").get_data(as_text=True)
    assert "Chat is resting" in html and "Opens" in html and "9:00 AM" in html
    assert 'href="tel:988"' in html and 'href="/safety-plan"' in html and 'href="/help"' in html
    assert 'href="/logout"' in html and '<nav aria-label="Study"' not in html
    assert 'http-equiv="refresh"' in html


def test_the_resting_screen_sends_you_home_once_open(study, login_as, v2, hours, monkeypatch):
    from llm_chat.utils import access_hours
    monkeypatch.setattr(access_hours, "within_access_window", lambda *a, **k: True)
    resp = login_as(study["patient"]).get("/closed")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")


# ── Read-only: reading stays open, replying waits ──

def test_read_only_keeps_home_with_a_notice(study, login_as, v2, hours):
    hours("read_only")
    html = login_as(study["patient"]).get("/dashboard").get_data(as_text=True)
    assert "Closed for now" in html and "You can still read your past chats." in html
    assert login_as(study["patient"]).get("/closed").status_code == 302


def test_read_only_exercise_reads_but_does_not_reply(study, login_as, v2, hours):
    hours("read_only")
    html = login_as(study["patient"]).get(f"/exercise/{study['thoughts_conv'].id}").get_data(as_text=True)
    assert "Chat is resting" in html and "You can still read this chat and your notebook." in html
    assert 'id="composer"' not in html and html.count("data-message-id") == 4


@pytest.mark.parametrize("mode", ["lock", "read_only"])
def test_sending_is_refused_in_both_modes(study, login_as, hours, mode):
    hours(mode)
    resp = login_as(study["patient"]).post(f"/api/conversation/{study['thoughts_conv'].id}/message",
                                           json={"message": "hello", "client_message_id": "closed-hours-test"})
    assert resp.status_code == 403 and resp.get_json()["outside_access_hours"] is True


def test_todays_page_is_unchanged(study, login_as, hours):
    """v1: /dashboard is today's page, which shows its own resting cover."""
    html = login_as(study["patient"]).get("/dashboard").get_data(as_text=True)
    assert 'id="homeView"' in html and 'id="accessClosedOverlay"' in html
