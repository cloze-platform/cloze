"""Shared pytest fixtures for Cloze.

Sets environment defaults *before* importing the application so that
`create_app()` builds an isolated, in-memory test instance.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from llm_chat import create_app
from llm_chat.extensions import db as _db
from llm_chat.models.core import User


@pytest.fixture
def app():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    """The active SQLAlchemy session/handle, inside the app context."""
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Clear the module-global IP rate-limit state between tests so login
    tests don't leak attempt counts into one another."""
    from llm_chat.routes import auth as auth_module
    auth_module._login_attempts.clear()
    yield
    auth_module._login_attempts.clear()


@pytest.fixture
def make_user(app):
    """Factory: create and persist a User with a known password."""
    def _make(username, role="user", password="pw-12345", **kwargs):
        user = User(
            username=username,
            email=kwargs.pop("email", f"{username}@example.test"),
            role=role,
            **kwargs,
        )
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        return user
    return _make


@pytest.fixture
def login_as(app):
    """Return a fresh test client already authenticated as `user`, by seeding
    the Flask-Login session cookie directly (see flask_login_test_pattern).

    A new client per call avoids cross-identity session bleed that occurs when
    one client's session cookie is rewritten between requests.
    """
    def _login(user):
        # Tests run inside a single app context, and Flask-Login caches the
        # resolved user on `g`. Clear it so switching identity mid-test takes
        # effect instead of returning the previously cached user.
        from flask import g
        g.pop("_login_user", None)

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
        return c
    return _login
