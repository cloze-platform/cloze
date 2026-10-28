import time
import requests
from ..extensions import db

class Model(db.Model):
    __tablename__ = 'models'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(50))
    model_identifier = db.Column(db.String(100))
    api_endpoint = db.Column(db.String(200))
    config = db.Column(db.Text)
    is_available = db.Column(db.Boolean, default=False)
    last_availability_check = db.Column(db.Float)
    visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Float, default=lambda: time.time())

    def check_availability(self):
        if self.provider == 'local':
            return self._check_local_availability()
        try:
            from ..services.llm_interface import LLMInterface
            if self.provider in LLMInterface._provider_clients:
                return True
            else:
                return False
        except Exception:
            return False

    def _check_local_availability(self):
        if not self.api_endpoint:
            return False
        try:
            # Ollama uses /api/tags for health check
            base_url = self.api_endpoint.replace('/v1/chat/completions', '')
            response = requests.get(f"{base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False


class Conversation(db.Model):
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200))
    model_id = db.Column(db.Integer, db.ForeignKey('models.id'), nullable=False)
    system_prompt_id = db.Column(db.Integer, db.ForeignKey('system_prompts.id'), nullable=True)
    system_prompt_content = db.Column(db.Text)
    # New fields for clinician-controlled chats
    window_id = db.Column(db.Integer, db.ForeignKey('chat_windows.id'), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('chat_templates.id'), nullable=True)
    visible = db.Column(db.Boolean, default=True)
    consent_provided = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, onupdate=lambda: time.time())

    messages = db.relationship(
        'Message',
        backref='conversation',
        lazy='dynamic', 
        cascade='all, delete-orphan',
        order_by='Message.timestamp' 
    )
    model = db.relationship('Model')
    system_prompt = db.relationship('SystemPrompt')

    def to_dict(self, include_messages=True):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'model': self.model.name if self.model else None,
            'system_prompt_id': self.system_prompt_id,
            'system_prompt_content': self.system_prompt_content,
            'visible': self.visible,
            'consent_provided': self.consent_provided,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if include_messages:
            data['messages'] = [
                m.to_dict()
                for m in self.messages.order_by(Message.timestamp).all()
            ]
        return data

    def generate_title(self):
        first_msg = self.messages.filter_by(role='user').first()
        if first_msg:
            self.title = first_msg.content[:50] + ('...' if len(first_msg.content) > 50 else '')


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.Float, nullable=False, index=True)
    token_count = db.Column(db.Integer)
    response_time = db.Column(db.Float)

    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp
        }


class SavedSelection(db.Model):
    __tablename__ = 'saved_selections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    selection_text = db.Column(db.Text, nullable=False)
    message_ids = db.Column(db.Text)
    note = db.Column(db.Text)
    created_at = db.Column(db.Float, default=lambda: time.time())
