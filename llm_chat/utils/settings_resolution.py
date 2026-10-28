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


def get_provider_id_for_patient(patient_id):
    """Look up the provider_id for a given patient. Returns None if unassigned.

    Deterministic: ProviderPatient has a unique constraint on patient_id,
    so each patient has at most one provider.
    """
    from ..models import ProviderPatient
    assignment = ProviderPatient.query.filter_by(patient_id=patient_id).first()
    return assignment.provider_id if assignment else None
