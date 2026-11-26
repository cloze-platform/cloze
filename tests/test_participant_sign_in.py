"""Sign in on the redesigned pages (participant_ui = v2)."""

import time

import pytest


def test_v1_keeps_todays_sign_in(client):
    html = client.get("/login").get_data(as_text=True)
    assert "selectRole" in html and 'id="sign-in"' not in html


def test_v2_sign_in_has_no_role_picker(client, v2):
    html = client.get("/login").get_data(as_text=True)
    assert 'id="sign-in"' in html and "selectRole" not in html and "role-btn" not in html
    assert 'autocomplete="username"' in html and 'autocomplete="current-password"' in html
    assert 'href="tel:988"' in html and "Researchers sign in here too." in html
    assert '<nav aria-label="Study"' not in html and "help-dialog" not in html


def test_signed_in_users_go_to_their_dashboard(client, v2, make_user, login_as):
    resp = login_as(make_user("p1")).get("/login")
    assert resp.status_code == 302


def test_signed_out_pages_send_you_to_the_new_sign_in(client, v2):
    resp = client.get("/notebook")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert 'id="sign-in"' in client.get(resp.headers["Location"]).get_data(as_text=True)


def test_a_locked_account_answers_like_a_wrong_password(client, make_user, db, v2):
    user = make_user("p1")
    user.locked_until = time.time() + 600
    db.session.commit()
    resp = client.post("/api/login", json={"username": "p1", "password": "pw-12345"})
    assert resp.status_code == 401 and resp.get_json() == {"status": "error", "message": "Invalid credentials"}
    assert "signing in pauses for 15 minutes" in client.get("/login").get_data(as_text=True)


@pytest.mark.parametrize("role, target", [("user", "/dashboard"), ("provider", "/provider/dashboard")])
def test_each_account_goes_to_its_own_dashboard(client, v2, make_user, role, target):
    make_user("someone", role=role)
    resp = client.post("/api/login", json={"username": "someone", "password": "pw-12345"})
    assert resp.status_code == 200 and resp.get_json()["redirect"].endswith(target)
