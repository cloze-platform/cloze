"""Report generation switches.

CLOZE_REPORTS_ENABLED=false turns report generation off for the whole
instance: no NLP analysis or AI summary runs anywhere, whatever admins or
providers have chosen. Chat windows still move through their statuses so the
app keeps working normally.
"""
import json
import time

import pytest

from llm_chat.extensions import db as _db
from llm_chat.models import AdminSettings, ProviderFeatureFlags, Report
from llm_chat.models.chat_window import ChatWindow
from llm_chat.models.core import ProviderPatient
from llm_chat.services.report_utils import finalize_expired_windows
from llm_chat.utils.settings_resolution import get_effective_setting

DAY = 86400
JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def provider(make_user):
    return make_user("prov", role="provider")


@pytest.fixture
def patient(make_user, provider):
    p = make_user("pt", role="user")
    _db.session.add(ProviderPatient(provider_id=provider.id, patient_id=p.id))
    _db.session.commit()
    return p


@pytest.fixture
def ended_window(provider, patient):
    """A window whose end date has passed but whose report hasn't run yet."""
    now = time.time()
    window = ChatWindow(
        patient_id=patient.id, provider_id=provider.id, title="Week 1",
        start_date=now - 2 * DAY, end_date=now - DAY, status="active",
    )
    _db.session.add(window)
    _db.session.commit()
    return window


@pytest.fixture
def reports_off(app):
    app.config["CLOZE_REPORTS_ENABLED"] = False


@pytest.fixture
def generation_forbidden(monkeypatch):
    """Fail the test if anything tries to build a report."""
    from report.generator import UnifiedReportGenerator

    def _fail(*args, **kwargs):
        raise AssertionError("report generation must not run")

    monkeypatch.setattr(UnifiedReportGenerator, "save_report", _fail)
    monkeypatch.setattr(UnifiedReportGenerator, "generate", _fail)


def _enable_everywhere(provider):
    """Admin and provider settings both say reports are on."""
    _db.session.add(AdminSettings(setting_name="enable_nlp_report", setting_value=json.dumps(True)))
    _db.session.add(ProviderFeatureFlags(provider_id=provider.id, enable_nlp_report=True))
    _db.session.commit()


# --- The instance switch -----------------------------------------------------

def test_switch_overrides_admin_and_provider_settings(app, provider):
    _enable_everywhere(provider)
    assert get_effective_setting("enable_nlp_report", provider.id, True) is True

    app.config["CLOZE_REPORTS_ENABLED"] = False
    assert get_effective_setting("enable_nlp_report", provider.id, True) is False
    assert get_effective_setting("enable_nlp_report", None, True) is False


def test_switch_only_affects_reports(app, provider):
    app.config["CLOZE_REPORTS_ENABLED"] = False
    _db.session.add(ProviderFeatureFlags(provider_id=provider.id, require_safety_plan=True))
    _db.session.commit()
    assert get_effective_setting("require_safety_plan", provider.id, False) is True


def test_ended_window_finishes_without_a_report(
    reports_off, generation_forbidden, provider, ended_window
):
    _enable_everywhere(provider)

    finalize_expired_windows()

    assert _db.session.get(ChatWindow, ended_window.id).status == "report_ready"
    assert Report.query.count() == 0


@pytest.mark.parametrize("path", ["/api/reports/window/{id}/generate",
                                  "/api/reports/window/{id}/generate-unified"])
def test_generate_endpoints_refuse(
    reports_off, generation_forbidden, login_as, provider, ended_window, path
):
    _enable_everywhere(provider)
    client = login_as(provider)

    resp = client.post(path.format(id=ended_window.id), json={}, headers=JSON_HEADERS)

    assert resp.status_code == 403


def test_live_report_refused_when_switch_off(
    reports_off, generation_forbidden, login_as, provider, ended_window
):
    resp = login_as(provider).get(f"/api/reports/live/{ended_window.id}")
    assert resp.status_code == 403


# --- The live report used to ignore the admin setting ----------------------------

def test_live_report_respects_admin_setting(
    generation_forbidden, login_as, provider, patient, ended_window
):
    _db.session.add(AdminSettings(setting_name="enable_nlp_report", setting_value=json.dumps(False)))
    _db.session.commit()

    for user in (provider, patient):
        resp = login_as(user).get(f"/api/reports/live/{ended_window.id}")
        assert resp.status_code == 403
