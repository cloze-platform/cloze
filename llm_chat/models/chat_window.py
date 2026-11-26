import time
import json
from ..extensions import db

class ChatWindow(db.Model):
    """Represents a time-bounded chat window created by a clinician for a patient"""
    __tablename__ = 'chat_windows'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Float, nullable=False)  # Unix timestamp
    end_date = db.Column(db.Float, nullable=False)    # Unix timestamp
    visible = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default='scheduled', nullable=False)
    flow_name = db.Column(db.String(200), nullable=True)   # Name of the StudyFlow that generated this window
    phase_label = db.Column(db.String(200), nullable=True)  # Phase name, cycle label, or null for always-available
    # FK to the generating flow (report-v2 scope resolution). flow_name predates
    # this and is kept for display; legacy rows have flow_id NULL — the scope
    # resolver falls back to a flow_name match for those.
    flow_id = db.Column(db.Integer, db.ForeignKey('study_flows.id'), nullable=True, index=True)
    # FK to the generating phase. Needed to backfill templates into the right
    # window when a chat is added to an already-enrolled always-available flow;
    # matching on title == phase.name would break the moment a phase is renamed.
    phase_id = db.Column(db.Integer, db.ForeignKey('flow_phases.id'), nullable=True, index=True)
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    # Report configuration (JSON string storing enabled components)
    report_config = db.Column(db.Text, default='{"ai_summary": true, "saved_messages": true, "descriptive_stats": true, "nlp_analysis": true, "cooccurrence_analysis": true}')

    # Relationships
    patient = db.relationship('User', foreign_keys=[patient_id], backref='chat_windows')
    provider = db.relationship('User', foreign_keys=[provider_id])
    templates = db.relationship('ChatTemplate', backref='window', lazy='dynamic', cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='chat_window', lazy='dynamic')

    # compute_status values. A closed window has ended, its report made or not.
    OPEN, UPCOMING = 'active', 'scheduled'
    CLOSED_STATUSES = ('generating_report', 'report_ready')

    def is_current(self):
        """Check if this window is currently active based on date"""
        return self.compute_status() == 'active'

    @property
    def is_active(self):
        """Compatibility shim for legacy code paths."""
        return self.visible and self.compute_status() == 'active'

    def compute_status(self, now=None):
        """Return the status string based on timing and current state."""
        now = now or time.time()

        # Terminal states: these persist regardless of time
        if self.status in self.CLOSED_STATUSES:
            return self.status

        if now < self.start_date:
            return 'scheduled'
        if self.start_date <= now <= self.end_date:
            return 'active'

        return 'generating_report'

    def sync_status(self, now=None):
        """Update persisted status to match the computed status."""
        new_status = self.compute_status(now)
        if self.status != new_status:
            self.status = new_status
        return self.status

    def is_upcoming(self, now=None):
        """Check if this window is scheduled for the future"""
        return self.compute_status(now) == 'scheduled'

    def get_report_config(self):
        """Get report configuration as normalized v2 dict."""
        from report.config import normalize_config, get_default_config
        try:
            raw = json.loads(self.report_config or '{}')
            return normalize_config(raw)
        except Exception:
            return get_default_config()

    def set_report_config(self, config):
        """Set report configuration from dict"""
        self.report_config = json.dumps(config)

    def get_report_type(self):
        """Get the report type from config."""
        config = self.get_report_config()
        return config.get('report_type', 'summary')

    def to_dict(self):
        status_value = self.compute_status()
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'provider_id': self.provider_id,
            'title': self.title,
            'description': self.description,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'visible': self.visible,
            'status': status_value,
            'is_current': self.is_current(),
            'is_upcoming': self.is_upcoming(),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'report_config': self.get_report_config(),
        }


class ChatTemplate(db.Model):
    """Predefined chat configuration within a window"""
    __tablename__ = 'chat_templates'

    id = db.Column(db.Integer, primary_key=True)
    window_id = db.Column(db.Integer, db.ForeignKey('chat_windows.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    purpose = db.Column(db.Text)  # Description of what this chat is for
    model_id = db.Column(db.Integer, db.ForeignKey('models.id'), nullable=False)
    system_prompt_id = db.Column(db.Integer, db.ForeignKey('system_prompts.id'), nullable=True)
    custom_system_prompt = db.Column(db.Text)  # If not using a predefined prompt
    max_messages = db.Column(db.Integer)  # Optional limit on messages in this chat
    order_index = db.Column(db.Integer, default=0)  # Display order
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Float, default=lambda: time.time())
    # The study-design chat this was generated from, if any. Settings are copied
    # at enrollment; ones that should follow later edits are read through this
    # link instead (services/flow_links.py).
    flow_chat_id = db.Column(db.Integer, db.ForeignKey('flow_chats.id', ondelete='SET NULL'),
                             nullable=True, index=True)

    # Relationships
    model = db.relationship('Model')
    system_prompt = db.relationship('SystemPrompt')
    flow_chat = db.relationship('FlowChat')

    def get_system_prompt_content(self):
        """Get the actual system prompt content to use.

        Composes the system prompt from layers:
        1. Universal (always) — forbidden content, AI honesty, crisis, platform, guardrails
        2. Clinical safety (when is_clinical_use = true)
        3. Monitoring disclosure (team-written)
        4. Persona (default or provider override)
        5. Interaction context (default or provider override)
        6. Domain (anxiety, depression, etc.)
        7. Custom instructions (per conversation)
        8. Safety plan (when clinical + plan exists)
        """
        from prompts.composer import compose_system_prompt
        from .settings import ProviderFeatureFlags

        domain_id = None
        if self.system_prompt and self.system_prompt.domain_prompt_id:
            domain_id = self.system_prompt.domain_prompt_id

        # Load provider feature flags
        flags = None
        if self.window and self.window.provider_id:
            flags = ProviderFeatureFlags.query.filter_by(
                provider_id=self.window.provider_id
            ).first()

        # Resolve settings from flags (NULL = default)
        is_clinical = flags.is_clinical_use if (flags and flags.is_clinical_use is not None) else True
        monitoring_disclosure = flags.monitoring_disclosure if flags else None
        persona_override = flags.persona_override if flags else None
        interaction_context_override = flags.system_context_override if flags else None

        # Load patient's active safety plan (gracefully handle missing)
        safety_plan_data = None
        if self.window and self.window.patient_id:
            from .safety_plan import SafetyPlan
            active_plan = SafetyPlan.query.filter_by(
                patient_id=self.window.patient_id, status='active'
            ).first()
            if active_plan:
                safety_plan_data = active_plan.to_prompt_dict()

        # Build custom instructions from system prompt content + per-template overrides
        custom_parts = []
        if self.system_prompt and self.system_prompt.content and not domain_id:
            # SystemPrompt has content but no domain — it IS the custom prompt
            # (e.g., the Ann & Alex homework protocol)
            custom_parts.append(self.system_prompt.content)
        if self.custom_system_prompt and self.custom_system_prompt.strip():
            custom_parts.append(self.custom_system_prompt.strip())
        custom_instructions = '\n\n'.join(custom_parts) if custom_parts else None

        return compose_system_prompt(
            is_clinical_use=is_clinical,
            monitoring_disclosure=monitoring_disclosure,
            persona_override=persona_override,
            interaction_context_override=interaction_context_override,
            domain_id=domain_id,
            custom_instructions=custom_instructions,
            safety_plan=safety_plan_data,
        )

    def to_dict(self):
        return {
            'id': self.id,
            'window_id': self.window_id,
            'title': self.title,
            'purpose': self.purpose,
            'model': self.model.name if self.model else None,
            'model_id': self.model_id,
            'system_prompt_id': self.system_prompt_id,
            'custom_system_prompt': self.custom_system_prompt,
            'max_messages': self.max_messages,
            'order_index': self.order_index,
            'visible': self.visible,
            'created_at': self.created_at
        }
