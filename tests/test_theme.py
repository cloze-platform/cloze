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


# ── Participant tokens (templates/participant/_tokens.html) ─────────────────

from llm_chat.theme import contrast, participant_css, participant_tokens  # noqa: E402

# (text, background) token pairs the participant designs put together. Each
# must reach WCAG AA (4.5:1) in light and dark mode, for the Cloze palette and
# for a custom deployment palette.
_READABLE_PAIRS = [
    ("ink", "page"), ("ink", "surface"), ("ink", "quiet"), ("ink", "menu"), ("ink", "accent-soft"),
    ("ink-3", "page"), ("ink-3", "quiet"),
    ("hint", "page"), ("hint", "surface"), ("hint", "quiet"), ("hint", "menu"),
    ("accent-ink", "page"), ("accent-ink", "accent-soft"),
    ("on-accent", "accent"),
    ("done", "page"), ("done", "done-soft"),
    ("waiting", "waiting-soft"),
    ("help", "help-soft"), ("help", "page"),
    ("night-ink", "night"), ("night-muted", "night"), ("night-muted", "night-raised"),
    ("night-link", "night"), ("night-help", "night-raised"), ("night-help", "night-help-soft"),
    # The notebook's paper.
    ("ink", "paper"), ("ink-2", "paper"), ("ink-3", "paper"), ("paper-hint", "paper"), ("paper-hint", "desk"),
    ("pen", "paper"), ("ink", "desk"), ("on-accent", "accent"),
]


@pytest.mark.parametrize("raw", [None, BIDMC], ids=["cloze", "bidmc"])
@pytest.mark.parametrize("mode", [0, 1], ids=["light", "dark"])
@pytest.mark.parametrize("fg, bg", _READABLE_PAIRS)
def test_participant_text_colours_are_readable(raw, mode, fg, bg):
    tokens = participant_tokens(load_theme(raw))[mode]
    assert contrast(tokens[fg], tokens[bg]) >= 4.5, f"{fg} on {bg}: {contrast(tokens[fg], tokens[bg]):.2f}"


def test_contrast_matches_known_values():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert contrast("#777777", "#777777") == 1


def test_participant_tokens_follow_the_instance_palette():
    light, dark = participant_tokens(load_theme(BIDMC))
    assert light["accent"] == dark["accent"] == "#1C488F"
    assert dark["page"] == "#161B24"  # the instance's dark_page
    assert light["accent-soft"] != participant_tokens(load_theme(None))[0]["accent-soft"]


def test_a_light_primary_gets_dark_text_on_buttons():
    light, _ = participant_tokens(load_theme('{"primary": "#F4D35E"}'))
    assert light["on-accent"] == "#18181F"


def test_participant_css_has_light_and_dark_sets():
    css = participant_css(load_theme(None))
    assert css.startswith(":root { --p-accent: #5B5FC7;")
    assert "@media (prefers-color-scheme: dark) { :root {" in css
    assert css.count("--p-page:") == 2
