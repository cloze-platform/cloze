"""Smoke tests: the application builds and core routes are wired.

These are intentionally minimal — a green baseline to build a real suite on.
Priority targets for the next tests: role-based access control
(@role_required), one-provider-per-participant isolation, and prompt
composition (compose_system_prompt layering).
"""


def test_app_factory_builds(app):
    assert app is not None
    # Core blueprints are registered.
    for bp in ("auth", "provider", "admin"):
        assert bp in app.blueprints


def test_login_route_exists(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/login" in rules


def test_login_page_responds(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_health_check_needs_no_login(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "ok"
