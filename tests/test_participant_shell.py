"""The redesigned participant shell: base template, tokens and icons."""
import pytest
from flask import render_template_string

from llm_chat.utils.icons import ICONS, icon, status_icon


def test_icons_are_decorative_svg():
    svg = str(icon("home", size=20, cls="text-p-hint"))
    assert svg.startswith('<svg aria-hidden="true" focusable="false" class="text-p-hint" width="20" height="20"')
    assert ICONS["home"] in svg


def test_unknown_icon_names_fail_loudly():
    with pytest.raises(KeyError):
        icon("hoem")
    with pytest.raises(KeyError):
        status_icon("done")


def test_icon_class_is_escaped():
    assert '"><script>' not in str(icon("home", cls='"><script>'))


@pytest.mark.parametrize("state", ["finished", "started", "not_started"])
def test_status_icons_use_participant_tokens(state):
    assert "var(--p-" in str(status_icon(state))


def _render_shell(app):
    with app.test_request_context("/"):
        return render_template_string(
            '{% extends "participant/base.html" %}'
            '{% block content %}<h1>Hello</h1>{{ icon("home") }}{% endblock %}'
        )


def test_shell_renders_with_tokens_font_and_landmarks(app):
    html = _render_shell(app)
    assert "--p-accent:" in html and "prefers-color-scheme: dark" in html
    assert "/static/fonts/figtree/figtree-latin-wght-normal.woff2" in html
    assert 'href="#main"' in html and '<main id="main"' in html
    assert 'aria-live="polite"' in html
    assert "<h1>Hello</h1>" in html


def test_shell_loads_no_google_fonts(app):
    assert "fonts.googleapis.com" not in _render_shell(app)


def test_figtree_is_served(client):
    resp = client.get("/static/fonts/figtree/figtree-latin-wght-normal.woff2")
    assert resp.status_code == 200
    assert resp.data[:4] == b"wOF2"
