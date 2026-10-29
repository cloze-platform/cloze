"""Instance colour theme (CLOZE_THEME)."""
import pytest

from llm_chat.config import ConfigError, load_config
from llm_chat.theme import DEFAULTS, DERIVED_DEFAULTS, SOFT_DEFAULTS, css_variables, load_theme

BIDMC = '{"primary": "#1c488f", "hover": "#223D71", "accent": "#469CD9", "dark_page": "#161B24"}'


def test_defaults_are_the_cloze_palette():
    theme = load_theme(None)
    assert {k: theme[k] for k in DEFAULTS} == DEFAULTS
    assert theme["soft"] == SOFT_DEFAULTS


def test_overrides_merge_over_defaults():
    theme = load_theme(BIDMC)
    assert theme["primary"] == "#1C488F"      # normalised to upper case
    assert theme["accent"] == "#469CD9"
    assert theme["tint"] == DEFAULTS["tint"]  # not overridden


def test_custom_primary_gets_a_matching_soft_ramp():
    soft = load_theme(BIDMC)["soft"]
    assert soft[600] == "#1C488F" and soft[700] == "#223D71"
    assert soft[50] != SOFT_DEFAULTS[50]
    assert soft[50] > soft[400]  # lighter shades are closer to white


def test_overriding_other_colours_keeps_the_default_ramp():
    assert load_theme('{"dark_page": "#000000"}')["soft"] == SOFT_DEFAULTS


@pytest.mark.parametrize("raw, message", [
    ("not json", "not valid JSON"),
    ('["#1C488F"]', "must be a JSON object"),
    ('{"primray": "#1C488F"}', "unknown keys: primray"),
    ('{"primary": "blue"}', "#RRGGBB"),
    ('{"primary": "#1C488"}', "#RRGGBB"),
])
def test_invalid_themes_fail_at_startup(monkeypatch, raw, message):
    monkeypatch.setenv("CLOZE_THEME", raw)
    with pytest.raises(ConfigError, match=message):
        load_config()


def test_css_variables_have_hex_and_rgb_forms():
    css = css_variables(load_theme(BIDMC))
    assert "--brand-primary: #1C488F; --brand-primary-rgb: 28 72 143;" in css
    assert "--dark-page: #161B24;" in css
    assert "--soft-50:" in css and "--soft-700-rgb:" in css


def test_pages_default_to_the_cloze_theme(client):
    html = client.get("/login").get_data(as_text=True)
    assert "--brand-primary: #5B5FC7;" in html
    assert "rgb(var(--brand-primary-rgb) / <alpha-value>)" in html


def test_theme_reaches_the_page(monkeypatch):
    monkeypatch.setenv("CLOZE_THEME", BIDMC)
    from llm_chat import create_app
    themed = create_app()
    html = themed.test_client().get("/login").get_data(as_text=True)
    assert "--brand-primary: #1C488F;" in html
    assert "#5B5FC7" not in html  # no hardcoded Cloze colour left on the page


def test_chat_and_action_colours_follow_a_custom_theme():
    assert load_theme(None)["derived"] == DERIVED_DEFAULTS  # Cloze keeps its exact values
    derived = load_theme(BIDMC)["derived"]
    assert derived["action"] == "#223D71" and derived["action-hover"] == "#1C488F"
    assert derived["chat-page-dark"] == "#161B24"
    assert derived["bubble"] != DERIVED_DEFAULTS["bubble"]
