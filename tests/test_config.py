"""Configuration: every setting comes from llm_chat.config, and production
refuses to start when something required is missing."""
import sys
import types

import pytest

from llm_chat.config import ConfigError, load_config

CONFIG_VARS = (
    "FLASK_ENV", "SECRET_KEY", "DATABASE_URL", "CLOZE_PUBLIC_URL",
    "CLOZE_GUARD_SENDER", "AWS_SES_REGION", "CLOZE_GUARD_AWS_PROFILE",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OLLAMA_HOST",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Start each test with none of the config variables set (a developer's
    .env is loaded at import time and would otherwise leak in)."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _production(env, **overrides):
    values = {
        "FLASK_ENV": "production",
        "SECRET_KEY": "s" * 64,
        "DATABASE_URL": "postgresql://cloze:pw@db.internal/cloze?sslmode=require",
    }
    values.update(overrides)
    for name, value in values.items():
        env.setenv(name, value)


# --- Development defaults ----------------------------------------------------

def test_development_defaults(clean_env):
    config = load_config()
    assert config["PRODUCTION"] is False
    assert config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///llm_chat.db"
    assert len(config["SECRET_KEY"]) == 64  # random per process
    assert config["SESSION_COOKIE_SECURE"] is False
    assert config["CLOZE_PUBLIC_URL"] == "http://localhost:5051"
    assert config["OLLAMA_HOST"] == "http://localhost:11434"
    assert config["CLOZE_GUARD_SENDER"] is None


def test_empty_values_count_as_unset(clean_env):
    clean_env.setenv("SECRET_KEY", "   ")
    clean_env.setenv("OPENAI_API_KEY", "")
    config = load_config()
    assert config["SECRET_KEY"].strip()  # generated, not the blank value
    assert config["OPENAI_API_KEY"] is None


def test_trailing_slashes_are_trimmed(clean_env):
    clean_env.setenv("CLOZE_PUBLIC_URL", "https://cloze.example.org/")
    clean_env.setenv("OLLAMA_HOST", "http://10.0.0.5:11434/")
    config = load_config()
    assert config["CLOZE_PUBLIC_URL"] == "https://cloze.example.org"
    assert config["OLLAMA_HOST"] == "http://10.0.0.5:11434"


# --- Production checks ---------------------------------------------------------

def test_valid_production_config(clean_env):
    _production(clean_env)
    config = load_config()
    assert config["PRODUCTION"] is True
    assert config["SECRET_KEY"] == "s" * 64
    assert config["SESSION_COOKIE_SECURE"] is True


def test_production_requires_secret_key(clean_env):
    _production(clean_env, SECRET_KEY="")
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        load_config()


def test_production_requires_database_url(clean_env):
    _production(clean_env, DATABASE_URL="")
    with pytest.raises(ConfigError, match="DATABASE_URL is not set"):
        load_config()


def test_production_rejects_sqlite(clean_env):
    _production(clean_env, DATABASE_URL="sqlite:///llm_chat.db")
    with pytest.raises(ConfigError, match="PostgreSQL"):
        load_config()


def test_production_guard_email_needs_public_url(clean_env):
    _production(clean_env, CLOZE_GUARD_SENDER="noreply@cloze.example.org")
    with pytest.raises(ConfigError, match="CLOZE_PUBLIC_URL"):
        load_config()

    clean_env.setenv("CLOZE_PUBLIC_URL", "https://cloze.example.org")
    assert load_config()["CLOZE_GUARD_SENDER"] == "noreply@cloze.example.org"


def test_production_reports_every_problem_at_once(clean_env):
    _production(clean_env, SECRET_KEY="", DATABASE_URL="")
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert "SECRET_KEY" in str(excinfo.value)
    assert "DATABASE_URL" in str(excinfo.value)


# --- Guard alert email reads its settings from the app config ----------------------

class _FakeSES:
    def __init__(self, sent):
        self._sent = sent

    def send_email(self, **kwargs):
        self._sent.append(kwargs)


def _fake_boto3(calls, sent):
    def session(profile_name=None):
        calls["profile"] = profile_name

        class _Session:
            def client(self, service, region_name=None):
                calls["service"], calls["region"] = service, region_name
                return _FakeSES(sent)
        return _Session()
    return types.SimpleNamespace(Session=session)


def test_guard_email_uses_configured_sender_region_and_link(app, monkeypatch):
    from llm_chat.services.notifications import send_guard_email

    calls, sent = {}, []
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(calls, sent))
    app.config.update(
        CLOZE_GUARD_SENDER="noreply@cloze.example.org",
        AWS_SES_REGION="us-east-2",
        CLOZE_GUARD_AWS_PROFILE=None,
        CLOZE_PUBLIC_URL="https://cloze.example.org",
    )

    send_guard_email("a@example.test, b@example.test", patient_id=98761)

    assert calls == {"profile": None, "service": "ses", "region": "us-east-2"}
    assert len(sent) == 1
    message = sent[0]
    assert message["Source"] == "noreply@cloze.example.org"
    assert message["Destination"]["ToAddresses"] == ["a@example.test", "b@example.test"]
    text = message["Message"]["Body"]["Text"]["Data"]
    html = message["Message"]["Body"]["Html"]["Data"]
    assert "https://cloze.example.org/provider/dashboard" in text
    assert 'href="https://cloze.example.org/provider/dashboard"' in html
    # The alert must never identify the participant.
    for part in (message["Message"]["Subject"]["Data"], text, html):
        assert "98761" not in part


def test_guard_email_skipped_without_sender(app, monkeypatch):
    from llm_chat.services.notifications import send_guard_email

    calls, sent = {}, []
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(calls, sent))
    app.config["CLOZE_GUARD_SENDER"] = None

    send_guard_email("a@example.test")

    assert sent == [] and calls == {}
