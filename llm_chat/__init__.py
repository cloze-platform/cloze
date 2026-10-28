from pathlib import Path
from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import load_config
from .extensions import db, migrate, login_manager
from .routes.auth import auth_bp
from .routes.auth import auth_blp
from .routes.conversations import conv_bp
from .routes.provider import provider_bp
from .routes.admin import admin_bp
from .routes.chat_windows import window_bp
from .routes.reports import reports_bp
from .routes.safety_plan import safety_bp
from flask_smorest import Api

# Load variables from .env - use explicit path to ensure it's found
# Get the project root directory (two levels up from this file)
project_root = Path(__file__).parent.parent
env_path = project_root / '.env'
if not env_path.exists():
    print(f"WARNING: .env file not found at {env_path}")
else:
    load_dotenv(dotenv_path=env_path)
    print(f"✓ Loaded environment variables from {env_path}")

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    # Trust proxy headers (for Cloudflare/reverse proxy HTTPS)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # All environment-driven settings; raises ConfigError if production is misconfigured.
    app.config.update(load_config())
    app.config.update(
        API_TITLE="My API",
        API_VERSION="v1",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    )
    api = Api(app)

    # CSRF protection for JSON API endpoints
    # Reject state-changing requests without application/json content type.
    # Browsers won't send cross-origin JSON without a CORS preflight,
    # which we don't allow, so this blocks cross-site request forgery.
    @app.before_request
    def csrf_protect():
        from flask import request, abort
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            # Skip for non-API routes (form-based pages) and logout
            if request.path.startswith('/api/'):
                content_type = request.content_type or ''
                if 'application/json' not in content_type and 'multipart/form-data' not in content_type:
                    abort(415)

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if app.config["PRODUCTION"]:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # User loader
    from .models.core import User
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Blueprints
    api.register_blueprint(auth_blp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(conv_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(window_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(safety_bp)

    # Error pages
    from flask import render_template as _rt

    @app.errorhandler(403)
    def forbidden(e):
        return _rt('403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return _rt('404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return _rt('500.html'), 500

    # Load balancer health check. Skips the database, so a DB blip doesn't restart every task.
    @app.get("/healthz")
    def healthz():
        return "ok"

    # Start report scheduler (5-minute interval)
    from .services.report_scheduler import report_scheduler
    report_scheduler.init_app(app)
    with app.app_context():
        report_scheduler.start()

    # Initialize LLM provider clients
    from .services.llm_interface import LLMInterface
    LLMInterface.initialize_clients(app.config)

    return app
