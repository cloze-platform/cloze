import time
from collections import defaultdict
from flask import Blueprint, render_template, jsonify, redirect, url_for, request
from flask_login import login_user, logout_user, login_required, current_user
from ..models.core import User
from ..extensions import db
from flask_smorest import Blueprint as SmorestBlueprint

# IP-based rate limiting for login: an IP with 10 failed attempts in a minute is
# refused until the window passes. Only failures count, so many participants
# signing in from one clinic network don't lock each other out. The client IP
# comes from ProxyFix (see CLOZE_PROXY_HOPS); per-process, in memory.
_login_attempts = defaultdict(list)  # ip -> [timestamps of failed attempts]
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 10  # failed attempts per window


def _is_rate_limited(ip):
    now = time.time()
    recent = [t for t in _login_attempts.get(ip, ()) if now - t < _RATE_LIMIT_WINDOW]
    if recent:
        _login_attempts[ip] = recent
    else:
        _login_attempts.pop(ip, None)  # don't keep an entry for every IP ever seen
    return len(recent) >= _RATE_LIMIT_MAX


def _record_failure(ip):
    _login_attempts[ip].append(time.time())

auth_bp = Blueprint("auth1", __name__)
auth_blp = SmorestBlueprint(name = "auth", import_name = "auth", description = "Authentication endpoints")

@auth_blp.route("/")
@auth_blp.response(302, description="Redirects to login or dashboard")
def index():
    """Redirect based on authentication status"""
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin.admin_dashboard'))
        elif current_user.is_provider():
            return redirect(url_for('provider.provider_dashboard'))
        else:
            return redirect(url_for('conversations.user_dashboard'))
    return redirect(url_for('auth.login'))

@auth_blp.route("/login")
def login():
    """Render the login page. With the redesigned participant pages on
    (participant_ui = v2), everyone signs in on the new page; researchers and
    admins use it too."""
    from ..utils.participant_ui import uses_v2
    if uses_v2():
        if current_user.is_authenticated:
            return redirect(url_for('auth.index'))
        return render_template("participant/sign_in.html")
    return render_template("login.html")

@auth_blp.route("/admin/login")
def admin_login():
    """Render the admin login page"""
    if current_user.is_authenticated and current_user.is_admin():
        return redirect(url_for('admin.admin_dashboard'))
    return render_template("admin_login.html")

@auth_blp.route("/logout")
@login_required
def logout():
    """Logout endpoint"""
    logout_user()
    return redirect(url_for('auth.login'))

# admin/provider login
@auth_blp.route("/api/login", methods=["POST"])
@auth_blp.response(401, description="Invalid credentials")
def api_login():
    """Perform authentication (check user, password), if valid then log user in"""
    ip = request.remote_addr or 'unknown'

    # IP-based rate limiting
    if _is_rate_limited(ip):
        return jsonify({'status': 'error', 'message': 'Too many login attempts. Please wait a minute.'}), 429

    data = request.json or {}
    user = User.query.filter_by(username=data.get('username')).first()

    if user:
        # Account lockout check
        if user.is_locked:
            _record_failure(ip)
            remaining = int(user.locked_until - time.time())
            mins = max(1, remaining // 60)
            return jsonify({'status': 'error', 'message': f'Account temporarily locked. Try again in {mins} minute(s).',
                            'retry_after_minutes': mins}), 423

        if user.check_password(data.get('password', '')):
            user.record_successful_login()
            db.session.commit()
            login_user(user)
            return jsonify({
                'status': 'success',
                'role': user.role,
                'redirect': url_for('admin.admin_dashboard' if user.is_admin()
                                    else 'provider.provider_dashboard' if user.is_provider()
                                    else 'conversations.user_dashboard')
            })
        else:
            user.record_failed_login()
            db.session.commit()

    _record_failure(ip)
    return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401
