"""Tests for the login flow: success, generic failure (no account
enumeration), account lockout, IP rate limiting, and logout gating."""


def _login(client, username, password, headers=None):
    return client.post("/api/login", json={"username": username, "password": password},
                       headers=headers)


def test_login_page_renders(client):
    assert client.get("/login").status_code == 200


def test_successful_login_returns_role_and_redirect(client, make_user):
    make_user("prov", role="provider", password="pw-12345")
    resp = _login(client, "prov", "pw-12345")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["role"] == "provider"
    assert "redirect" in body


def test_wrong_password_is_generic_401(client, make_user):
    make_user("prov", role="provider", password="pw-12345")
    resp = _login(client, "prov", "nope")
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "Invalid credentials"


def test_unknown_user_response_matches_wrong_password(client, make_user):
    """No account enumeration: an unknown username and a wrong password for a
    real user must be indistinguishable (same status + message)."""
    make_user("real", role="user", password="pw-12345")
    unknown = _login(client, "ghost", "whatever")
    wrong = _login(client, "real", "whatever")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()


def test_account_locks_after_five_failures(client, make_user):
    make_user("victim", role="user", password="pw-12345")
    for _ in range(5):
        assert _login(client, "victim", "bad").status_code == 401
    # Now locked: even the right password is refused, in the same words as
    # for an unknown user, so neither the account nor the password shows.
    locked = _login(client, "victim", "pw-12345")
    unknown = _login(client, "ghost", "pw-12345")
    assert locked.status_code == unknown.status_code == 401
    assert locked.get_json() == unknown.get_json()


def test_wrong_tries_while_locked_do_not_extend_the_lock(client, make_user, db):
    user = make_user("victim", role="user", password="pw-12345")
    for _ in range(5):
        _login(client, "victim", "bad")
    until = db.session.get(type(user), user.id).locked_until
    _login(client, "victim", "bad")
    assert db.session.get(type(user), user.id).locked_until == until


def test_an_expired_lock_starts_the_count_again(client, make_user, db, monkeypatch):
    import time
    make_user("victim", role="user", password="pw-12345")
    for _ in range(5):
        _login(client, "victim", "bad")
    later = time.time() + 901
    monkeypatch.setattr(time, "time", lambda: later)
    assert _login(client, "victim", "bad").status_code == 401        # one wrong try after the lock ran out
    assert _login(client, "victim", "pw-12345").status_code == 200   # ...doesn't lock it again


def test_ip_rate_limit_after_ten_attempts(client, make_user):
    # Unknown user avoids per-account lockout so we isolate the IP limiter.
    for _ in range(10):
        assert _login(client, "ghost", "bad").status_code == 401
    assert _login(client, "ghost", "bad").status_code == 429


def test_successful_logins_do_not_use_up_the_ip_limit(client, make_user):
    """Many participants signing in from one clinic network must not trip the
    limiter: only failed attempts count."""
    make_user("p1", role="user", password="pw-12345")
    for _ in range(15):
        assert _login(client, "p1", "pw-12345").status_code == 200


def test_ip_limit_keys_on_the_forwarded_client_address(client):
    """Behind Cloudflare every request comes from a Cloudflare address. The
    limiter must use the client address the proxy appends (the last
    X-Forwarded-For entry), not the proxy's, and not a value the client made up."""
    for i in range(10):
        spoofed = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"}
        assert _login(client, "ghost", "bad", headers=spoofed).status_code == 401
    limited = _login(client, "ghost", "bad", headers={"X-Forwarded-For": "203.0.113.7"})
    assert limited.status_code == 429
    # Another client behind the same proxy is unaffected.
    other = _login(client, "ghost", "bad", headers={"X-Forwarded-For": "198.51.100.20"})
    assert other.status_code == 401


def test_logout_requires_authentication(client):
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
