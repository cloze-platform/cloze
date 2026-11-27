import json
import time
from ..extensions import db


class StudyFlow(db.Model):
    """A reusable study structure that generates ChatWindows on enrollment."""
    __tablename__ = 'study_flows'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    flow_type = db.Column(db.String(20), nullable=False)  # 'always', 'phased', 'recurring'

    # Recurring-specific
    cadence_days = db.Column(db.Integer, nullable=True)
    cycle_count = db.Column(db.Integer, nullable=True)

    # Report settings (inherited by generated windows)
    report_config = db.Column(db.Text, nullable=True)  # JSON

    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    # Relationships
    provider = db.relationship('User', foreign_keys=[provider_id])
    phases = db.relationship('FlowPhase', backref='flow', cascade='all, delete-orphan',
                             order_by='FlowPhase.order_index')
    enrollments = db.relationship('FlowEnrollment', backref='flow', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'name': self.name,
            'flow_type': self.flow_type,
            'cadence_days': self.cadence_days,
            'cycle_count': self.cycle_count,
            'report_config': self.report_config,
            'created_at': self.created_at,
            'phases': [p.to_dict() for p in self.phases],
            # Withdrawn enrollments stay on the row but shouldn't inflate the count.
            'enrollment_count': sum(1 for e in self.enrollments if e.is_active),
        }


class FlowPhase(db.Model):
    """A phase within a study flow: one group of chats on the participant's
    Home and menu. Phased flows date each phase; always-available flows can
    have several undated ones. Recurring flows use only their first."""
    __tablename__ = 'flow_phases'

    NAME_LIMIT = 200
    DESCRIPTION_LIMIT = 300
    DEFAULT_ALWAYS_NAME = 'Always Available'

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey('study_flows.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    # The line under the group's name on the participant's Home card.
    description = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, default=0)

    # Relative timing (days from enrollment)
    start_day = db.Column(db.Integer, default=0)
    end_day = db.Column(db.Integer, nullable=True)  # NULL = no end (always available)

    # Relationships
    chats = db.relationship('FlowChat', backref='phase', cascade='all, delete-orphan',
                            order_by='FlowChat.order_index')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'order_index': self.order_index,
            'start_day': self.start_day,
            'end_day': self.end_day,
            'chats': [c.to_dict() for c in self.chats],
        }


class FlowChat(db.Model):
    """A chat template definition within a flow phase."""
    __tablename__ = 'flow_chats'

    id = db.Column(db.Integer, primary_key=True)
    phase_id = db.Column(db.Integer, db.ForeignKey('flow_phases.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    purpose = db.Column(db.Text, nullable=True)
    model_id = db.Column(db.Integer, db.ForeignKey('models.id'), nullable=False)
    system_prompt_id = db.Column(db.Integer, db.ForeignKey('system_prompts.id'), nullable=True)
    custom_system_prompt = db.Column(db.Text, nullable=True)
    max_messages = db.Column(db.Integer, nullable=True)
    order_index = db.Column(db.Integer, default=0)
    # Greeting shown in an empty chat; each part falls back to the researcher's
    # default (ProviderFeatureFlags.greeting_*). Read when the chat is opened,
    # not copied at enrollment, so edits reach participants already enrolled.
    greeting_text = db.Column(db.Text, nullable=True)
    greeting_asset_id = db.Column(db.Integer, db.ForeignKey('media_assets.id', ondelete='SET NULL'),
                                  nullable=True)
    # The chat's cast: a JSON list of the researcher's Speaker ids, in order,
    # and the main speaker (one of them, or none). Only chats with a cast have
    # their replies split by speaker. Read when the chat is shown, like the
    # greeting. A JSON list rather than a join table: deleted speakers are
    # skipped, and no foreign key can block deleting either side.
    speaker_ids = db.Column(db.Text, nullable=True)
    main_speaker_id = db.Column(db.Integer, nullable=True)
    # The chat's guide (a Guide id, read live), whether it opens beside the
    # chat the first time, and whether the model is given its text. No
    # foreign key, for the same reasons as the cast.
    guide_id = db.Column(db.Integer, nullable=True)
    guide_opens_on_start = db.Column(db.Boolean, nullable=True, default=False)
    guide_to_model = db.Column(db.Boolean, nullable=True, default=False)

    # Relationships
    model = db.relationship('Model')
    system_prompt = db.relationship('SystemPrompt')
    greeting_asset = db.relationship('MediaAsset', foreign_keys=[greeting_asset_id])

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'purpose': self.purpose,
            'model_id': self.model_id,
            'model_name': self.model.name if self.model else None,
            'system_prompt_id': self.system_prompt_id,
            'system_prompt_name': self.system_prompt.name if self.system_prompt else None,
            'custom_system_prompt': self.custom_system_prompt,
            'max_messages': self.max_messages,
            'order_index': self.order_index,
            'greeting_text': self.greeting_text,
            'greeting_asset': self.greeting_asset.to_dict() if self.greeting_asset else None,
            'speaker_ids': self.cast_ids,
            'main_speaker_id': self.main_speaker_id,
            'guide_id': self.guide_id,
            'guide_opens_on_start': bool(self.guide_opens_on_start),
            'guide_to_model': bool(self.guide_to_model),
        }

    @property
    def cast_ids(self):
        """The cast's speaker ids, in order ([] when there's no cast)."""
        try:
            ids = json.loads(self.speaker_ids) if self.speaker_ids else []
        except (TypeError, ValueError):
            return []
        return [i for i in ids if isinstance(i, int) and not isinstance(i, bool)] if isinstance(ids, list) else []


class FlowEnrollment(db.Model):
    """Tracks which patients are enrolled in which flows.

    Withdrawal is a soft delete: the row survives with status='withdrawn' so
    historical conversations, reports, and the report-v2 'enrollment' scope
    (which persists this row's id in ReportJob.scope_id) stay resolvable.
    """
    __tablename__ = 'flow_enrollments'

    STATUS_ACTIVE = 'active'
    STATUS_WITHDRAWN = 'withdrawn'

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey('study_flows.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    enrolled_at = db.Column(db.Float, default=lambda: time.time())
    # Rows predating withdrawal support have status NULL, which reads as active.
    # Always test membership with is_active / the active_filter() clause rather
    # than `status == 'active'`, which would silently exclude those legacy rows.
    status = db.Column(db.String(20), nullable=True, default=STATUS_ACTIVE)
    withdrawn_at = db.Column(db.Float, nullable=True)

    # Relationships
    patient = db.relationship('User', foreign_keys=[patient_id])

    __table_args__ = (db.UniqueConstraint('flow_id', 'patient_id'),)

    @property
    def is_active(self):
        return self.status != self.STATUS_WITHDRAWN

    @classmethod
    def active_filter(cls):
        """NULL-safe SQL clause for 'not withdrawn'.

        `status != 'withdrawn'` alone drops legacy NULL rows, since NULL != x
        evaluates to NULL rather than true.
        """
        from sqlalchemy import or_
        return or_(cls.status.is_(None), cls.status != cls.STATUS_WITHDRAWN)

    def to_dict(self):
        return {
            'id': self.id,
            'flow_id': self.flow_id,
            'patient_id': self.patient_id,
            'patient_name': self.patient.username if self.patient else None,
            'enrolled_at': self.enrolled_at,
            'status': self.status or self.STATUS_ACTIVE,
            'withdrawn_at': self.withdrawn_at,
        }
