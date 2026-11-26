"""
Settings resolution: ProviderFeatureFlags (non-NULL) > AdminSettings > hardcoded default.
"""

import json

from flask import current_app

from ..models import AdminSettings, ProviderFeatureFlags


def _get_admin_setting(name, default=None):
    """Read a single global admin setting value."""
    row = AdminSettings.query.filter_by(setting_name=name).first()
    if not row or not row.setting_value:
        return default
    try:
        return json.loads(row.setting_value)
    except Exception:
        return row.setting_value


def get_effective_setting(setting_name, provider_id=None, default=None):
    """Resolve a setting: ProviderFeatureFlags (if non-NULL) > AdminSettings > default.

    Args:
        setting_name: Must match a column name on ProviderFeatureFlags AND/OR
                      a setting_name in AdminSettings.
        provider_id:  The provider's user ID.  If None, falls through to global.
        default:      Hardcoded fallback if neither layer has a value.
    """
    # The instance-wide report switch (CLOZE_REPORTS_ENABLED) wins over both layers.
    if setting_name == 'enable_nlp_report' and not current_app.config["CLOZE_REPORTS_ENABLED"]:
        return False
    if provider_id:
        flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first()
        if flags:
            val = getattr(flags, setting_name, None)
            if val is not None:
                return val
    return _get_admin_setting(setting_name, default)


class Settings:
    """Effective settings for one provider, read from the database once: the
    provider's flags row, and all AdminSettings rows the first time one is
    needed. The same rules as get_effective_setting; use it where a request
    reads several settings (the participant pages, sending a message)."""

    def __init__(self, provider_id):
        self.provider_id = provider_id
        self._flags = (ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first()
                       if provider_id else None)
        self._admin = None

    def _admin_settings(self):
        if self._admin is None:
            self._admin = {}
            for row in AdminSettings.query.all():
                if row.setting_value:
                    try:
                        self._admin[row.setting_name] = json.loads(row.setting_value)
                    except Exception:
                        self._admin[row.setting_name] = row.setting_value
        return self._admin

    def get(self, name, default=None):
        if name == 'enable_nlp_report' and not current_app.config["CLOZE_REPORTS_ENABLED"]:
            return False
        if self._flags is not None:
            value = getattr(self._flags, name, None)
            if value is not None:
                return value
        return self._admin_settings().get(name, default)


def get_provider_id_for_patient(patient_id):
    """Look up the provider_id for a given patient. Returns None if unassigned.

    Deterministic: ProviderPatient has a unique constraint on patient_id,
    so each patient has at most one provider.
    """
    from ..models import ProviderPatient
    assignment = ProviderPatient.query.filter_by(patient_id=patient_id).first()
    return assignment.provider_id if assignment else None
