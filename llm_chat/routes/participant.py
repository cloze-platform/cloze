"""The redesigned participant pages (participant_ui = v2).

Server-rendered pages under templates/participant/. Home stays at /dashboard,
which hands participants here when the switch is on (see
conversations.user_dashboard). Today's JSON APIs are unchanged; these pages
call them.
"""

from flask import Blueprint, render_template

participant_bp = Blueprint("participant", __name__, url_prefix="")


def render_home():
    return render_template("participant/home.html")
