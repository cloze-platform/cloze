import json
import time
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from ..extensions import db
from ..models import ChatWindow, ChatTemplate, User, Conversation, SafetyPlan, ProviderFeatureFlags
from ..utils.settings_resolution import get_effective_setting

window_bp = Blueprint("chat_windows", __name__, url_prefix="/api/windows")

@window_bp.route("/", methods=["GET"])
@login_required
def get_chat_windows():
    """Get chat windows for current user or managed patients"""
    if current_user.is_patient():
        # Get visible windows for current patient
        windows = ChatWindow.query.filter_by(patient_id=current_user.id, visible=True).all()
    elif current_user.is_provider():
        # Get windows for all patients managed by provider
        patient_id = request.args.get('patient_id')
        if patient_id:
            # Check if provider manages this patient
            if not current_user.can_access_patient(int(patient_id)):
                abort(403)
            windows = ChatWindow.query.filter_by(patient_id=patient_id).all()
        else:
            windows = ChatWindow.query.filter_by(provider_id=current_user.id).all()
    else:
        abort(403)

    # Include templates for each window
    result = []
    for window in windows:
        window_data = window.to_dict()
        window_data['templates'] = [t.to_dict() for t in window.templates.filter_by(visible=True).order_by(ChatTemplate.order_index).all()]

        # Add patient name for provider view
        if current_user.is_provider() or current_user.is_admin():
            patient = db.session.get(User, window.patient_id)
            window_data['patient_name'] = patient.username if patient else 'Unknown'

        # Check if conversations exist for each template
        for template in window_data['templates']:
            existing_conv = Conversation.query.filter_by(
                user_id=window.patient_id,
                window_id=window.id,
                template_id=template['id']
            ).first()
            template['has_conversation'] = existing_conv is not None
            template['conversation_id'] = existing_conv.id if existing_conv else None

        result.append(window_data)

    return jsonify(result)


@window_bp.route("/<int:window_id>", methods=["GET"])
@login_required
def get_chat_window(window_id):
    """Get detailed data for a specific window (for editing)"""
    if not current_user.is_provider():
        abort(403)

    window = db.get_or_404(ChatWindow, window_id)

    # Check if provider owns this window
    if window.provider_id != current_user.id:
        abort(403)

    # Get templates for this window
    templates = ChatTemplate.query.filter_by(window_id=window_id).order_by(ChatTemplate.order_index).all()

    window_data = window.to_dict()
    window_data['templates'] = [
        {
            'id': t.id,
            'title': t.title,
            'purpose': t.purpose,
            'model_id': t.model_id,
            'system_prompt_id': t.system_prompt_id,
            'custom_system_prompt': t.custom_system_prompt,
            'max_messages': t.max_messages,
            'order_index': t.order_index
        }
        for t in templates
    ]
    window_data['report_config'] = window.get_report_config()

    return jsonify(window_data)


@window_bp.route("/current", methods=["GET"])
@login_required
def get_current_windows():
    """Get active chat windows for the patient (current and upcoming)"""
    if not current_user.is_patient():
        abort(403)

    windows = [
        w for w in ChatWindow.query.filter_by(
            patient_id=current_user.id,
            visible=True
        ).all()
        if w.is_current()
    ]

    # Include templates for each active window
    result = []
    for window in windows:
        window_data = window.to_dict()
        window_data['templates'] = [t.to_dict() for t in window.templates.filter_by(visible=True).order_by(ChatTemplate.order_index).all()]
        # Check if conversations already exist for each template
        for template in window_data['templates']:
            existing_conv = Conversation.query.filter_by(
                user_id=current_user.id,
                window_id=window.id,
                template_id=template['id']
            ).first()
            template['has_conversation'] = existing_conv is not None
            template['conversation_id'] = existing_conv.id if existing_conv else None
        result.append(window_data)

    return jsonify(result)

@window_bp.route("/", methods=["POST"])
@login_required
def create_chat_window():
    """Create a new chat window (provider only)"""
    if not current_user.is_provider():
        abort(403)

    data = request.json or {}

    # Validate patient access
    patient_id = data.get('patient_id')
    if not current_user.can_access_patient(patient_id):
        abort(403)

    # Create window
    window = ChatWindow(
        patient_id=patient_id,
        provider_id=current_user.id,
        title=data.get('title'),
        description=data.get('description'),
        start_date=data.get('start_date'),
        end_date=data.get('end_date')
    )
    db.session.add(window)
    db.session.flush()  # Get the ID without committing
    window.status = window.compute_status()

    # Handle report configuration
    report_config = data.get('report_config')
    if report_config:
        window.set_report_config(report_config)
        print(f"Report config for window {window.id}: {report_config}")

    # Create templates
    can_set_custom_prompts = get_effective_setting('allow_custom_prompts', current_user.id, True)

    # Admin-enforced model allowlist for this provider
    flags = ProviderFeatureFlags.query.filter_by(provider_id=current_user.id).first()
    admin_allowed_models = json.loads(flags.allowed_models) if flags and flags.allowed_models else None

    templates = data.get('templates', [])
    for idx, template_data in enumerate(templates):
        custom_prompt = template_data.get('custom_system_prompt')
        if not can_set_custom_prompts:
            custom_prompt = None

        # Validate model against admin allowlist
        tmpl_model_id = template_data.get('model_id')
        if admin_allowed_models and tmpl_model_id not in admin_allowed_models:
            return jsonify({'error': f'Model {tmpl_model_id} is not permitted for this study'}), 403

        # Fall back to provider default prompt if none specified
        prompt_id = template_data.get('system_prompt_id')
        if not prompt_id and flags and flags.default_system_prompt_id:
            prompt_id = flags.default_system_prompt_id

        template = ChatTemplate(
            window_id=window.id,
            title=template_data.get('title'),
            purpose=template_data.get('purpose'),
            model_id=tmpl_model_id,
            system_prompt_id=prompt_id,
            custom_system_prompt=custom_prompt,
            max_messages=template_data.get('max_messages'),
            order_index=idx
        )
        db.session.add(template)

    window.status = window.compute_status()
    db.session.commit()
    return jsonify(window.to_dict())

@window_bp.route("/<int:window_id>", methods=["PUT"])
@login_required
def update_chat_window(window_id):
    """Update a chat window (provider only)"""
    if not current_user.is_provider():
        abort(403)

    window = db.get_or_404(ChatWindow, window_id)

    # Check if provider owns this window
    if window.provider_id != current_user.id:
        abort(403)

    data = request.json or {}

    # Update window fields
    if 'title' in data:
        window.title = data['title']
    if 'description' in data:
        window.description = data['description']
    if 'start_date' in data:
        window.start_date = data['start_date']
    if 'end_date' in data:
        window.end_date = data['end_date']
    if 'visible' in data:
        window.visible = data['visible']
    elif 'is_active' in data:
        window.visible = data['is_active']

    window.updated_at = time.time()

    # Update templates if provided
    if 'templates' in data:
        can_set_custom_prompts = get_effective_setting('allow_custom_prompts', current_user.id, True)

        # Admin-enforced model allowlist for this provider
        flags = ProviderFeatureFlags.query.filter_by(provider_id=current_user.id).first()
        admin_allowed_models = json.loads(flags.allowed_models) if flags and flags.allowed_models else None

        # Remove existing templates
        ChatTemplate.query.filter_by(window_id=window_id).delete()

        # Add new templates
        for idx, template_data in enumerate(data['templates']):
            custom_prompt = template_data.get('custom_system_prompt')
            if not can_set_custom_prompts:
                custom_prompt = None

            # Validate model against admin allowlist
            tmpl_model_id = template_data.get('model_id')
            if admin_allowed_models and tmpl_model_id not in admin_allowed_models:
                return jsonify({'error': f'Model {tmpl_model_id} is not permitted for this study'}), 403

            # Fall back to provider default prompt if none specified
            prompt_id = template_data.get('system_prompt_id')
            if not prompt_id and flags and flags.default_system_prompt_id:
                prompt_id = flags.default_system_prompt_id

            template = ChatTemplate(
                window_id=window_id,
                title=template_data.get('title'),
                purpose=template_data.get('purpose'),
                model_id=tmpl_model_id,
                system_prompt_id=prompt_id,
                custom_system_prompt=custom_prompt,
                max_messages=template_data.get('max_messages'),
                order_index=idx
            )
            db.session.add(template)

    # Handle report configuration
    report_config = data.get('report_config')
    if report_config:
        window.set_report_config(report_config)
        print(f"Updated report config for window {window.id}: {report_config}")

    db.session.commit()
    return jsonify(window.to_dict())

@window_bp.route("/<int:window_id>", methods=["DELETE"])
@login_required
def delete_chat_window(window_id):
    """Delete a chat window (provider only)"""
    if not current_user.is_provider():
        abort(403)

    window = db.get_or_404(ChatWindow, window_id)

    # Check if provider owns this window
    if window.provider_id != current_user.id:
        abort(403)

    # Check if there are any conversations in this window
    if window.conversations.count() > 0:
        # Instead of deleting, just deactivate it
        window.visible = False
        db.session.commit()
        return jsonify({'message': 'Window deactivated (has existing conversations)'})

    # If no conversations, safe to delete
    db.session.delete(window)
    db.session.commit()
    return jsonify({'message': 'Window deleted'})

@window_bp.route("/<int:window_id>/templates", methods=["POST"])
@login_required
def add_template_to_window(window_id):
    """Add a single template to an existing window (provider only)."""
    if not current_user.is_provider():
        abort(403)

    window = db.get_or_404(ChatWindow, window_id)
    if window.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    max_order = max([t.order_index for t in window.templates.all()], default=-1)

    template = ChatTemplate(
        window_id=window_id,
        title=data.get('title', 'New Chat'),
        purpose=data.get('purpose'),
        model_id=data['model_id'],
        system_prompt_id=data.get('system_prompt_id'),
        custom_system_prompt=data.get('custom_system_prompt'),
        max_messages=data.get('max_messages'),
        order_index=max_order + 1,
    )
    db.session.add(template)
    db.session.commit()
    return jsonify(template.to_dict()), 201


@window_bp.route("/start_conversation", methods=["POST"])
@login_required
def start_conversation_from_template():
    """Start a conversation from a chat template"""
    if not current_user.is_patient():
        abort(403)

    data = request.json or {}
    template_id = data.get('template_id')

    template = db.get_or_404(ChatTemplate, template_id)
    window = template.window

    # Check if window is for current patient and is active
    if window.patient_id != current_user.id or not window.is_current():
        abort(403)

    # Safety plan gating: patient must have an active (approved) safety plan
    if get_effective_setting('require_safety_plan', window.provider_id, True):
        active_plan = SafetyPlan.get_active_plan(current_user.id)
        if not active_plan:
            return jsonify({
                'error': 'You must have an approved safety plan before starting conversations. '
                         'Please complete your safety plan sections first.'
            }), 403

    # Check if conversation already exists for this template
    existing = Conversation.query.filter_by(
        user_id=current_user.id,
        window_id=window.id,
        template_id=template_id
    ).first()

    if existing:
        return jsonify({'conversation_id': existing.id, 'existing': True})

    # Create new conversation
    conversation = Conversation(
        user_id=current_user.id,
        title=template.title,
        model_id=template.model_id,
        system_prompt_id=template.system_prompt_id,
        system_prompt_content=template.get_system_prompt_content(),
        window_id=window.id,
        template_id=template_id
    )
    db.session.add(conversation)
    db.session.commit()

    return jsonify({'id': conversation.id, 'conversation_id': conversation.id, 'existing': False})
