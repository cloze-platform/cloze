"""Application configuration, read from the environment in one place.

Every environment variable Cloze reads is listed here with its default, so a
deployer has a single place to look. In production (FLASK_ENV=production) the
settings below are checked at startup, and a misconfigured instance refuses to
boot instead of half-working.
"""

import os
import secrets

from .theme import load_theme


class ConfigError(RuntimeError):
    """Raised at startup when production configuration is missing or invalid."""


def _env(name, default=None):
    """Read an environment variable, treating an empty string as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def _flag(name, default):
    """Read an on/off environment variable; anything unrecognised is an error."""
    value = _env(name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, got {value!r}")


def load_config():
    """Build the Flask config dict from the environment.

    Raises ConfigError in production if a required setting is missing.
    """
    production = _env("FLASK_ENV") == "production"
    secret_key = _env("SECRET_KEY")
    database_url = _env("DATABASE_URL")
    public_url = _env("CLOZE_PUBLIC_URL")
    guard_sender = _env("CLOZE_GUARD_SENDER")

    try:
        theme = load_theme(_env("CLOZE_THEME"))
    except ValueError as e:
        raise ConfigError(str(e)) from None

    if production:
        problems = []
        if not secret_key:
            problems.append("SECRET_KEY is not set (every restart would log everyone out)")
        if not database_url:
            problems.append("DATABASE_URL is not set")
        elif database_url.startswith("sqlite"):
            problems.append("DATABASE_URL points at SQLite; production needs PostgreSQL")
        if guard_sender and not public_url:
            problems.append(
                "CLOZE_GUARD_SENDER is set but CLOZE_PUBLIC_URL is not "
                "(Guard alert emails need it to link to this instance, e.g. https://cloze.example.org)"
            )
        if problems:
            raise ConfigError(
                "Invalid production configuration:\n  - " + "\n  - ".join(problems)
            )

    return {
        "PRODUCTION": production,
        # Dev fallback only: a random key means sessions reset on every restart.
        "SECRET_KEY": secret_key or secrets.token_hex(32),
        "SQLALCHEMY_DATABASE_URI": database_url or "sqlite:///llm_chat.db",
        # Setup only: the restricted user the web app connects as, which
        # `manage.py init-production` creates (see utils/db_roles.py).
        "CLOZE_APP_DATABASE_URL": _env("CLOZE_APP_DATABASE_URL"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # Instance-wide switch for report generation (NLP analysis and AI
        # summaries). When false it overrides every admin and provider setting.
        "CLOZE_REPORTS_ENABLED": _flag("CLOZE_REPORTS_ENABLED", True),
        # Instance colours: optional JSON overrides of the Cloze palette (see theme.py).
        "CLOZE_THEME": theme,
        # Base URL of this instance, used in links inside outgoing email.
        "CLOZE_PUBLIC_URL": (public_url or "http://localhost:5051").rstrip("/"),
        # LLM providers: each is enabled only if its key is set.
        "OPENAI_API_KEY": _env("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": _env("ANTHROPIC_API_KEY"),
        "GOOGLE_API_KEY": _env("GOOGLE_API_KEY"),
        "OLLAMA_HOST": _env("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
        # CLOZE-Guard alert email (AWS SES). No sender means alerts are not emailed.
        "CLOZE_GUARD_SENDER": guard_sender,
        "AWS_SES_REGION": _env("AWS_SES_REGION", "us-east-1"),
        # Local dev only: a named AWS profile. In production boto3 uses the
        # instance or task role.
        "CLOZE_GUARD_AWS_PROFILE": _env("CLOZE_GUARD_AWS_PROFILE"),
    }
