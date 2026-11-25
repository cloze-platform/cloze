"""Which participant interface this instance serves.

One platform-wide AdminSettings row, participant_ui. "v2" serves the
redesigned participant pages (templates/participant/); anything else, or no
row at all, keeps today's single-page dashboard (templates/user_dashboard.html).

Turn it on with POST /api/admin/settings {"participant_ui": "v2"} and roll
back by setting it to "v1". Researcher and admin pages don't change either way.
"""

from .settings_resolution import _get_admin_setting

SETTING = "participant_ui"
V1, V2 = "v1", "v2"


def participant_ui():
    """"v2" if the setting says so, otherwise "v1"."""
    value = _get_admin_setting(SETTING, V1)
    return V2 if str(value).strip().lower() == V2 else V1


def uses_v2():
    return participant_ui() == V2
