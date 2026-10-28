"""Database setup commands in manage.py: `init-production` and `create-admin`."""
import pytest

import manage
from llm_chat.models import ChatWindow, Model, SafetyPlan, SystemPrompt, User

STRONG = "Correct-Horse-9"


@pytest.fixture
def setup_app():
    """manage.py's own app (in-memory SQLite, from conftest's environment)."""
    with manage.app.app_context():
        manage.db.create_all()
        yield manage.app
        manage.db.session.remove()
        manage.db.drop_all()


def _type_at_prompts(monkeypatch, *replies):
    replies = iter(replies)
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt="": next(replies))


def test_init_production_seeds_reference_data_only(setup_app):
    manage.initialize_database(demo=False)

    assert Model.query.count() > 0
    assert SystemPrompt.query.count() > 0
    assert User.query.count() == 0
    assert ChatWindow.query.count() == 0
    assert SafetyPlan.query.count() == 0


def test_init_production_is_idempotent(setup_app):
    manage.initialize_database(demo=False)
    counts = (Model.query.count(), SystemPrompt.query.count())

    manage.initialize_database(demo=False)

    assert (Model.query.count(), SystemPrompt.query.count()) == counts


def test_create_admin(setup_app, monkeypatch):
    _type_at_prompts(monkeypatch, STRONG, STRONG)

    manage.create_admin("ops", "ops@example.test")

    admin = User.query.filter_by(username="ops").one()
    assert admin.role == "admin"
    assert admin.check_password(STRONG)


@pytest.mark.parametrize("replies, message", [
    (("short",), "at least 12 characters"),
    ((STRONG, STRONG + "x"), "don't match"),
])
def test_create_admin_rejects_bad_password(setup_app, monkeypatch, replies, message):
    _type_at_prompts(monkeypatch, *replies)

    with pytest.raises(SystemExit, match=message):
        manage.create_admin("ops", "ops@example.test")

    assert User.query.count() == 0


@pytest.mark.parametrize("username, email", [
    ("taken", "new@example.test"),
    ("new", "taken@example.test"),
])
def test_create_admin_refuses_existing_user(setup_app, monkeypatch, username, email):
    existing = User(username="taken", email="taken@example.test", role="user")
    existing.set_password(STRONG)
    manage.db.session.add(existing)
    manage.db.session.commit()
    _type_at_prompts(monkeypatch)  # fails the test if it prompts

    with pytest.raises(SystemExit, match="already exists"):
        manage.create_admin(username, email)

    assert User.query.count() == 1
