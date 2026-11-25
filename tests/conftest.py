"""Shared pytest fixtures for Cloze.

Sets environment defaults *before* importing the application so that
`create_app()` builds an isolated, in-memory test instance.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CLOZE_PROXY_HOPS", "1")  # one proxy in front, as in production

import time

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


# ── A seeded participant study (participant_nav and the participant pages) ──

NOW = 1_800_000_000.0
DAY = 86_400.0


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    return NOW


@pytest.fixture
def study(app, frozen, make_user):
    """A participant with windows in every state, plus another participant's
    window that must never show up. Time is frozen at NOW."""
    from llm_chat.models import ChatTemplate, ChatWindow, Conversation, Message, Model, ProviderPatient

    s = {}
    model = Model(name="test-model", provider="local", model_identifier="test")
    _db.session.add(model)
    _db.session.flush()
    provider = make_user("prov", role="provider")
    patient = make_user("pt")
    other = make_user("pt2")
    _db.session.add_all([ProviderPatient(provider_id=provider.id, patient_id=patient.id),
                         ProviderPatient(provider_id=provider.id, patient_id=other.id)])

    def window(title, start, end, user=patient, visible=True, status="scheduled", **kw):
        w = ChatWindow(patient_id=user.id, provider_id=provider.id, title=title,
                       description=f"About {title}", start_date=NOW + start, end_date=NOW + end,
                       visible=visible, status=status, created_at=NOW - 40 * DAY, **kw)
        _db.session.add(w)
        _db.session.flush()
        return w

    def template(w, title, order, visible=True):
        t = ChatTemplate(window_id=w.id, title=title, purpose=f"Purpose of {title}", model_id=model.id,
                         order_index=order, visible=visible, created_at=NOW - 40 * DAY)
        _db.session.add(t)
        _db.session.flush()
        return t

    def conversation(t=None, user=patient, messages=0, visible=True, updated=-DAY, title=None):
        c = Conversation(user_id=user.id, title=title or (t.title if t else "Free chat"), model_id=model.id,
                         window_id=t.window_id if t else None, template_id=t.id if t else None,
                         visible=visible, created_at=NOW + updated - 600, updated_at=NOW + updated)
        _db.session.add(c)
        _db.session.flush()
        for i in range(messages):
            _db.session.add(Message(conversation_id=c.id, role="user" if i % 2 == 0 else "assistant",
                                    content=f"message {i}", timestamp=NOW + updated - 500 + i))
        return c

    # Week 1: open now. One started, one not, one hidden template.
    s["week1"] = w1 = window("Week 1", -2 * DAY, 5 * DAY, flow_name="CBT", phase_label="Week 1")
    s["thoughts"] = t1 = template(w1, "Thought records", 0)
    s["checkin"] = template(w1, "Check-in", 1)
    template(w1, "Hidden chat", 2, visible=False)
    s["thoughts_conv"] = conversation(t1, messages=4, updated=-3600)
    # Week 2: opens in five days.
    s["week2"] = w2 = window("Week 2", 5 * DAY, 12 * DAY, flow_name="CBT", phase_label="Week 2")
    s["activation"] = template(w2, "Behavioural activation", 0)
    # Intro: ended three days ago, report not generated yet.
    s["intro"] = w3 = window("Intro", -10 * DAY, -3 * DAY, flow_name="CBT", phase_label="Intro")
    s["welcome_conv"] = conversation(template(w3, "Welcome", 0), messages=2, updated=-4 * DAY)
    template(w3, "Never started", 1)
    # Characters: always available; one conversation created but never sent to.
    s["characters"] = w5 = window("Characters", -30 * DAY, 300 * DAY, flow_name="Characters")
    s["sky"] = template(w5, "Sky", 0)
    s["star"] = star = template(w5, "Star", 1)
    s["star_conv"] = conversation(star, messages=0, updated=-2 * DAY)
    # Pilot: ended, report ready.
    s["pilot"] = w6 = window("Pilot", -60 * DAY, -50 * DAY, status="report_ready", flow_name="Pilot")
    s["pilot_conv"] = conversation(template(w6, "Pilot chat", 0), messages=2, updated=-50 * DAY)
    # A hidden window, open by date, with a conversation.
    s["hidden"] = w4 = window("Hidden window", -DAY, DAY, visible=False)
    conversation(template(w4, "Secret", 0), messages=2, updated=-600)
    # Conversations outside any window.
    conversation(messages=2, updated=-20 * DAY, title="Old free chat")
    conversation(messages=0, visible=False, updated=-21 * DAY, title="Empty hidden chat")
    conversation(messages=2, visible=False, updated=-22 * DAY, title="Hidden chat with messages")
    # Another participant's open window.
    w7 = window("Someone else's week", -DAY, DAY, user=other)
    conversation(template(w7, "Not yours", 0), user=other, messages=2)

    _db.session.commit()
    s.update(provider=provider, patient=patient, other=other, model=model)
    return s
