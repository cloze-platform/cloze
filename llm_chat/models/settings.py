import time
from ..extensions import db

class SystemPrompt(db.Model):
    """System prompts for conversations"""
    __tablename__ = 'system_prompts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    domain_prompt_id = db.Column(db.String(50), nullable=True)  # maps to prompts/domains/<id>.md
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Float, default=lambda: time.time())
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

class ProviderSettings(db.Model):
    """Settings that providers can configure for their patients"""
    __tablename__ = 'provider_settings'
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # NULL means applies to all patients
    allowed_models = db.Column(db.Text)  # JSON array of model IDs
    system_prompt_id = db.Column(db.Integer, db.ForeignKey('system_prompts.id'), nullable=True)
    time_window_start = db.Column(db.String(10))  # HH:MM format
    time_window_end = db.Column(db.String(10))    # HH:MM format
    max_messages_per_day = db.Column(db.Integer)
    custom_instructions = db.Column(db.Text)
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    # Relationships
    provider = db.relationship('User', foreign_keys=[provider_id])
    patient = db.relationship('User', foreign_keys=[patient_id])
    system_prompt = db.relationship('SystemPrompt')

class AdminSettings(db.Model):
    """Global admin settings for system control"""
    __tablename__ = 'admin_settings'
    id = db.Column(db.Integer, primary_key=True)
    setting_name = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)  # JSON value
    description = db.Column(db.Text)
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

class UserSettings(db.Model):
    """Admin-controlled settings for individual users"""
    __tablename__ = 'user_settings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    allowed_models = db.Column(db.Text)   # JSON array
    blocked_models = db.Column(db.Text)   # JSON array
    can_use_custom_prompts = db.Column(db.Boolean, default=True)
    can_save_selections = db.Column(db.Boolean, default=True)
    max_conversations_per_day = db.Column(db.Integer)
    max_messages_per_conversation = db.Column(db.Integer)
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    # Relationship
    user = db.relationship('User', backref='settings')


class ProviderFeatureFlags(db.Model):
    """Admin-controlled feature flags scoped to a specific provider.

    NULL on any column means "inherit the global AdminSettings default."
    """
    __tablename__ = 'provider_feature_flags'
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)

    # Safety
    require_safety_plan = db.Column(db.Boolean, nullable=True)
    allow_patient_anti_patterns = db.Column(db.Boolean, nullable=True)

    # NLP / Reports
    enable_nlp_report = db.Column(db.Boolean, nullable=True)
    report_config = db.Column(db.Text, nullable=True)  # JSON override

    # Prompts
    default_system_prompt_id = db.Column(db.Integer, db.ForeignKey('system_prompts.id'), nullable=True)
    allow_custom_prompts = db.Column(db.Boolean, nullable=True)

    # Model restrictions (admin-enforced allowlist)
    allowed_models = db.Column(db.Text, nullable=True)  # JSON array of model IDs

    # Prompt restrictions (admin-enforced allowlist)
    allowed_prompts = db.Column(db.Text, nullable=True)  # JSON array of system_prompt IDs

    # Conversation limits
    max_turns_per_conversation = db.Column(db.Integer, nullable=True)

    # Constitutional prompt configuration
    is_clinical_use = db.Column(db.Boolean, nullable=True)        # Loads clinical_safety.md when true
    monitoring_disclosure = db.Column(db.Text, nullable=True)     # Team-written monitoring disclosure text
    persona_override = db.Column(db.Text, nullable=True)          # Replaces defaults/persona.md

    # Configurable content
    safety_disclaimer_text = db.Column(db.Text, nullable=True)
    system_context_override = db.Column(db.Text, nullable=True)   # Replaces defaults/interaction_context.md

    # CLOZE-Guard v0 — keyword pre-classifier (None/False = off)
    guard_enabled = db.Column(db.Boolean, nullable=True)
    guard_keywords = db.Column(db.Text, nullable=True)            # JSON list[str]
    guard_notify_email = db.Column(db.Text, nullable=True)        # comma-separated recipients

    # CLOZE-Guard v0 — access-hours restriction (None/False = always available)
    access_hours_enabled = db.Column(db.Boolean, nullable=True)
    access_hours_start = db.Column(db.String(5), nullable=True)   # "09:00"
    access_hours_end = db.Column(db.String(5), nullable=True)     # "17:30"
    access_hours_timezone = db.Column(db.String(64), nullable=True)  # IANA, e.g. "America/New_York"
    access_hours_days = db.Column(db.Text, nullable=True)         # JSON list of weekday ints 0=Mon..6=Sun; NULL/empty = all days
    # Outside those hours, on the redesigned participant pages: 'lock' (NULL)
    # shows the resting screen instead of the site; 'read_only' keeps reading
    # open and pauses replying. Sending is refused in both.
    access_hours_mode = db.Column(db.String(16), nullable=True)

    # Greeting shown in an empty chat, unless the chat sets its own
    # (FlowChat.greeting_*). See services/greeting.py.
    greeting_text = db.Column(db.Text, nullable=True)
    # Need help?: the researcher's default for their chats (services/need_help.py), JSON.
    need_help = db.Column(db.Text, nullable=True)
    greeting_asset_id = db.Column(db.Integer, db.ForeignKey('media_assets.id', ondelete='SET NULL'),
                                  nullable=True)

    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    # Relationships
    provider = db.relationship('User', foreign_keys=[provider_id])
    default_system_prompt = db.relationship('SystemPrompt', foreign_keys=[default_system_prompt_id])
    greeting_asset = db.relationship('MediaAsset', foreign_keys=[greeting_asset_id])
