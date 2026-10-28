import json
import time
import secrets
from flask import Blueprint, render_template, jsonify, request, abort, redirect
from flask_login import current_user
from sqlalchemy import or_, and_
from sqlalchemy.exc import IntegrityError
from ..utils.decorators import role_required
from ..utils.passwords import validate_password
from ..extensions import db
from ..models import (User, Conversation, ProviderPatient, ProviderSettings,
                      ChatWindow, ChatTemplate, AuditLog, EscalationEvent, ProviderFeatureFlags, SystemPrompt,
                      StudyFlow, FlowPhase, FlowChat, FlowEnrollment)
from ..utils.settings_resolution import get_effective_setting

provider_bp = Blueprint("provider", __name__, url_prefix="")

@provider_bp.route("/provider/dashboard")
@role_required('provider', 'admin')
def provider_dashboard():
    return render_template("provider_dashboard.html")

@provider_bp.route("/provider/chat-windows")
@role_required('provider', 'admin')
def provider_chat_windows():
    return render_template("provider_chat_windows.html")

@provider_bp.route("/provider/chats")
@role_required('provider')
def provider_chats_page():
    return render_template("provider_chats.html")

@provider_bp.route("/provider/patient-progress")
@role_required('provider', 'admin')
def provider_patient_progress():
    patient_id = request.args.get('patient_id')
    if patient_id:
        return redirect('/provider/chats?patient_id=' + str(patient_id))
    return redirect('/provider/chats')

@provider_bp.route("/api/provider/patients")
@role_required('provider', 'admin')
def get_provider_patients():
    if current_user.is_admin():
        patients = User.query.filter_by(role='user').all()
    else:
        patient_ids = [pp.patient_id for pp in current_user.patients]
        patients = User.query.filter(User.id.in_(patient_ids)).all()

    def last_active_for(u: User):
        conv = u.conversations.order_by(Conversation.updated_at.desc()).first()
        return conv.updated_at if conv else None

    def visible_conversation_count(u: User):
        return Conversation.query.join(ChatWindow).filter(
            Conversation.user_id == u.id,
            ChatWindow.visible == True
        ).count()

    return jsonify([{
        'id': p.id,
        'username': p.username,
        'email': p.email,
        'conversation_count': visible_conversation_count(p),
        'last_active': last_active_for(p)
    } for p in patients])

@provider_bp.route("/api/provider/all-conversations")
@role_required('provider')
def get_all_provider_conversations():
    """Get all conversations AND unstarted templates across all patients."""
    patient_ids = [pp.patient_id for pp in current_user.patients]
    if not patient_ids:
        return jsonify([])

    # Build lookup maps
    patient_map = {p.id: p.username for p in User.query.filter(User.id.in_(patient_ids)).all()}

    # Get all windows for this provider
    windows = ChatWindow.query.filter_by(provider_id=current_user.id).all()
    window_map = {}
    for w in windows:
        window_map[w.id] = {
            'title': w.title,
            'status': w.compute_status(),
            'patient_id': w.patient_id,
            'flow_name': w.flow_name,
            'phase_label': w.phase_label,
        }

    # Get all started conversations
    conversations = Conversation.query.filter(
        Conversation.user_id.in_(patient_ids)
    ).order_by(Conversation.updated_at.desc()).all()

    # Track which template+patient combos have conversations
    started = set()
    result = []
    for c in conversations:
        if c.template_id:
            started.add((c.template_id, c.user_id))
        window = window_map.get(c.window_id, {})
        result.append({
            'id': c.id,
            'title': c.title or 'Untitled',
            'patient_id': c.user_id,
            'patient_name': patient_map.get(c.user_id, 'Unknown'),
            'model': c.model.name if c.model else None,
            'message_count': c.messages.count(),
            'created_at': c.created_at,
            'updated_at': c.updated_at,
            'window_title': window.get('title'),
            'window_status': window.get('status'),
            'flow_name': window.get('flow_name'),
            'phase_label': window.get('phase_label'),
            'is_started': True,
        })

    # Add unstarted templates as placeholder rows
    for w in windows:
        if not w.visible:
            continue
        templates = w.templates.filter_by(visible=True).all()
        for t in templates:
            if (t.id, w.patient_id) in started:
                continue
            ws = window_map.get(w.id, {})
            result.append({
                'id': None,
                'template_id': t.id,
                'title': t.title + ' (Not Started)',
                'patient_id': w.patient_id,
                'patient_name': patient_map.get(w.patient_id, 'Unknown'),
                'model': t.model.name if t.model else None,
                'message_count': 0,
                'created_at': w.created_at,
                'updated_at': None,
                'window_title': ws.get('title'),
                'window_status': ws.get('status'),
                'flow_name': ws.get('flow_name'),
                'phase_label': ws.get('phase_label'),
                'is_started': False,
            })

    # Sort: started conversations first (by updated_at desc), then unstarted
    result.sort(key=lambda x: (not x['is_started'], -(x['updated_at'] or x['created_at'] or 0)))
    return jsonify(result)


@provider_bp.route("/api/provider/patient/<int:patient_id>/conversations")
@role_required('provider', 'admin')
def get_patient_conversations(patient_id):
    if not current_user.can_access_patient(patient_id):
        abort(403)
    patient = User.query.get_or_404(patient_id)
    conversations = patient.conversations.order_by(Conversation.updated_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'title': c.title or 'Untitled',
        'model': c.model.name,
        'created_at': c.created_at,
        'message_count': c.messages.count()
    } for c in conversations])

@provider_bp.route("/api/provider/settings", methods=['GET', 'POST'])
@role_required('provider', 'admin')
def provider_settings():
    if request.method == 'POST':
        data = request.json or {}
        patient_id = data.get('patient_id')

        if not current_user.can_access_patient(patient_id):
            abort(403)

        settings = ProviderSettings.query.filter_by(
            provider_id=current_user.id, patient_id=patient_id
        ).first()

        if not settings:
            settings = ProviderSettings(provider_id=current_user.id, patient_id=patient_id)
            db.session.add(settings)

        settings.allowed_models = json.dumps(data.get('allowed_models', []))
        settings.system_prompt_id = data.get('system_prompt_id')
        settings.time_window_start = data.get('time_window_start')
        settings.time_window_end = data.get('time_window_end')
        settings.max_messages_per_day = data.get('max_messages_per_day')
        settings.custom_instructions = data.get('custom_instructions')
        db.session.commit()
        return jsonify({'status': 'success'})

    # GET
    patient_id = request.args.get('patient_id')
    settings = ProviderSettings.query.filter_by(
        provider_id=current_user.id, patient_id=patient_id
    ).first()

    if settings:
        return jsonify({
            'allowed_models': json.loads(settings.allowed_models or '[]'),
            'system_prompt_id': settings.system_prompt_id,
            'time_window_start': settings.time_window_start,
            'time_window_end': settings.time_window_end,
            'max_messages_per_day': settings.max_messages_per_day,
            'custom_instructions': settings.custom_instructions
        })
    return jsonify({})


# ── Patient creation & credential management ──────────────────

def _log_provider_action(action, target_type, target_id=None, details=None):
    entry = AuditLog(
        actor_id=current_user.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=json.dumps(details) if details else None,
    )
    db.session.add(entry)


def _next_patient_identity(provider):
    """Return the next sequential de-identified (username, email) for this
    provider, guaranteed free of both username *and* email collisions.

    Checking the email too is essential: a patient renamed before the
    email-sync fix can still hold a stale auto-generated email
    (e.g. ``<provider>User01@study.cloze.uk``) while no longer occupying that
    username. Generating purely from the next free username would then collide
    with that stale email on insert and raise IntegrityError.
    """
    prefix = provider.username + 'User'
    # `_` and `%` are LIKE wildcards, and provider usernames contain
    # underscores, so escape them to avoid over-matching unrelated accounts.
    escaped = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    existing = User.query.filter(
        User.username.like(escaped + '%', escape='\\'),
        User.role == 'user',
    ).all()
    max_num = 0
    for u in existing:
        suffix = u.username[len(prefix):]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))

    n = max_num + 1
    while True:
        username = f'{prefix}{n:02d}'
        email = f'{username}@study.cloze.uk'
        clash = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if clash is None:
            return username, email
        n += 1


@provider_bp.route("/api/provider/patients", methods=['POST'])
@role_required('provider')
def create_patient():
    """Provider creates a new de-identified patient."""
    data = request.json or {}
    count = min(int(data.get('count', 1)), 50)  # Cap at 50 per request

    created = []
    try:
        for _ in range(count):
            username, email = _next_patient_identity(current_user)
            password = secrets.token_hex(16)

            user = User(
                username=username,
                email=email,
                role='user',
                created_by=current_user.id,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()  # Get the user ID and surface any unique clash now

            assignment = ProviderPatient(
                provider_id=current_user.id,
                patient_id=user.id,
                assigned_by=current_user.id,
            )
            db.session.add(assignment)

            _log_provider_action('patient_created', 'user', user.id, {
                'username': username,
            })

            created.append({
                'id': user.id,
                'username': username,
                'password': password,
            })

        db.session.commit()
    except IntegrityError:
        # A concurrent create grabbed the same username/email between our check
        # and commit. Roll back rather than returning a 500 HTML page (which the
        # frontend would fail to parse as JSON).
        db.session.rollback()
        return jsonify({
            'status': 'error',
            'error': 'Could not allocate participant credentials, please try again.',
        }), 409

    return jsonify({'status': 'success', 'patients': created}), 201


@provider_bp.route("/api/provider/patients/<int:patient_id>/reset-password", methods=['POST'])
@role_required('provider')
def reset_patient_password(patient_id):
    """Provider resets a patient's password. Returns the new password once."""
    if not current_user.can_access_patient(patient_id):
        abort(403)

    patient = User.query.get_or_404(patient_id)
    if not patient.is_patient():
        return jsonify({'error': 'User is not a patient'}), 400

    # Optional provider-chosen password; blank/omitted -> auto-generate.
    data = request.get_json(silent=True) or {}
    custom = (data.get('password') or '').strip()
    if custom:
        err = validate_password(custom)
        if err:
            return jsonify({'status': 'error', 'error': err}), 400
        password = custom
    else:
        password = secrets.token_hex(16)

    patient.set_password(password)

    _log_provider_action('password_reset', 'user', patient_id, {'custom': bool(custom)})
    db.session.commit()

    return jsonify({
        'status': 'success',
        'username': patient.username,
        'password': password,
    })


@provider_bp.route("/api/provider/patients/<int:patient_id>/rename", methods=['POST'])
@role_required('provider')
def rename_patient(patient_id):
    """Provider changes a patient's username."""
    if not current_user.can_access_patient(patient_id):
        abort(403)

    patient = User.query.get_or_404(patient_id)
    if not patient.is_patient():
        return jsonify({'error': 'User is not a patient'}), 400

    data = request.json or {}
    new_username = (data.get('username') or '').strip()
    if not new_username:
        return jsonify({'error': 'Username is required'}), 400
    if len(new_username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    existing = User.query.filter_by(username=new_username).first()
    if existing and existing.id != patient_id:
        return jsonify({'error': 'Username already taken'}), 409

    old_username = patient.username
    patient.username = new_username
    # Keep email in sync to avoid unique constraint collisions on future patient creation
    patient.email = f'{new_username}@study.cloze.uk'

    _log_provider_action('rename_patient', 'user', patient_id,
                         {'from': old_username, 'to': new_username})
    db.session.commit()

    return jsonify({'status': 'success', 'username': new_username})


# ── Provider settings page ────────────────────────────────────

@provider_bp.route("/provider/settings")
@role_required('provider')
def provider_settings_page():
    return render_template("provider_settings.html")


@provider_bp.route("/api/provider/my-flags", methods=['GET'])
@role_required('provider')
def get_my_flags():
    """Provider reads their own feature flags (admin-set + editable content)."""
    flags = ProviderFeatureFlags.query.filter_by(provider_id=current_user.id).first()
    return jsonify({
        'is_clinical_use': get_effective_setting('is_clinical_use', current_user.id, True),
        'require_safety_plan': get_effective_setting('require_safety_plan', current_user.id, True),
        'enable_nlp_report': get_effective_setting('enable_nlp_report', current_user.id, True),
        'allow_custom_prompts': get_effective_setting('allow_custom_prompts', current_user.id, True),
        'max_turns_per_conversation': get_effective_setting('max_turns_per_conversation', current_user.id, None),
        'safety_disclaimer_text': flags.safety_disclaimer_text if flags else None,
        'system_context_override': flags.system_context_override if flags else None,
        'monitoring_disclosure': flags.monitoring_disclosure if flags else None,
        'persona_override': flags.persona_override if flags else None,
        # CLOZE-Guard v0
        'guard_enabled': bool(flags.guard_enabled) if flags else False,
        'guard_keywords': _json_list(flags.guard_keywords if flags else None),
        'guard_notify_email': flags.guard_notify_email if flags else None,
        'access_hours_enabled': bool(flags.access_hours_enabled) if flags else False,
        'access_hours_start': flags.access_hours_start if flags else None,
        'access_hours_end': flags.access_hours_end if flags else None,
        'access_hours_timezone': (flags.access_hours_timezone if flags else None) or 'America/New_York',
        'access_hours_days': _json_list(flags.access_hours_days if flags else None),
    })


def _json_list(raw):
    """Parse a JSON-array column into a Python list; [] on anything unparseable."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


@provider_bp.route("/api/provider/content-defaults", methods=['GET'])
@role_required('provider')
def get_content_defaults():
    """Returns the default safety disclaimer HTML and system context markdown."""
    from prompts.registry import PromptRegistry
    registry = PromptRegistry.instance()

    # Get default overridable prompt content
    persona_default = ''
    interaction_context_default = ''
    default_persona = registry.get_default_prompt('default_persona')
    if default_persona:
        persona_default = default_persona.content
    default_context = registry.get_default_prompt('default_interaction_context')
    if default_context:
        interaction_context_default = default_context.content

    # Default disclaimer HTML (the hardcoded modal body content)
    disclaimer_default = """<p class="mb-4 text-sm leading-relaxed text-stone-700">
  This conversation partner is designed for general discussion and support between your regular sessions.
  It is <strong>NOT</strong> a substitute for emergency services or crisis intervention.
</p>
<div class="rounded-lg border-l-4 border-amber-400 bg-amber-50 p-4 my-5">
  <h3 class="flex items-center gap-1.5 text-sm font-semibold text-amber-800 mb-2">Crisis Support</h3>
  <p class="text-sm text-amber-900 mb-2">If you are experiencing a mental health crisis, please:</p>
  <ul class="list-disc pl-5 text-sm text-amber-900 space-y-1">
    <li>Call <strong>988</strong> (Suicide &amp; Crisis Lifeline)</li>
    <li>Call <strong>911</strong> for immediate emergency assistance</li>
    <li>Contact your provider directly</li>
  </ul>
</div>
<div class="rounded-lg border-l-4 border-red-500 bg-red-50 p-4 my-5">
  <h3 class="flex items-center gap-1.5 text-sm font-semibold text-red-900 mb-2">Required Reporting</h3>
  <p class="text-sm text-red-900">
    For your safety, if you express active suicidal or homicidal thoughts with specific means or plans,
    we are required to notify your provider and may contact local authorities.
  </p>
</div>
<p class="text-sm text-stone-500 leading-relaxed mt-5">
  This conversation partner is here to support you between sessions, but it cannot provide clinical
  treatment or emergency intervention.
</p>
<div class="mt-5 pt-5 border-t border-stone-200">
  <label class="flex items-start gap-2.5 cursor-pointer select-none">
    <input type="checkbox" id="safetyAcknowledge" class="mt-0.5 h-4 w-4 cursor-pointer rounded border-stone-300 text-cloze-indigo focus:ring-cloze-indigo">
    <span class="text-sm text-stone-700">I understand this information and agree to use this conversation partner for general discussion only, not for clinical treatment or emergencies.</span>
  </label>
</div>"""

    return jsonify({
        'disclaimer_default': disclaimer_default,
        'persona_default': persona_default,
        'interaction_context_default': interaction_context_default,
        'system_context_default': interaction_context_default,  # backwards compat
    })


@provider_bp.route("/api/provider/my-flags", methods=['PUT'])
@role_required('provider')
def update_my_flags():
    """Provider updates their editable content fields."""
    data = request.json or {}
    flags = ProviderFeatureFlags.query.filter_by(provider_id=current_user.id).first()
    if not flags:
        flags = ProviderFeatureFlags(provider_id=current_user.id)
        db.session.add(flags)

    editable = ['safety_disclaimer_text', 'system_context_override', 'monitoring_disclosure', 'persona_override',
                'guard_notify_email', 'access_hours_start', 'access_hours_end', 'access_hours_timezone']
    for key in editable:
        if key in data:
            setattr(flags, key, data[key] or None)

    # Booleans: store explicit True/False (None only when absent)
    for key in ('guard_enabled', 'access_hours_enabled'):
        if key in data:
            setattr(flags, key, bool(data[key]))

    # JSON-array fields: accept a list, store as JSON string (None when empty)
    for key in ('guard_keywords', 'access_hours_days'):
        if key in data:
            val = data[key]
            if isinstance(val, list) and val:
                setattr(flags, key, json.dumps(val))
            else:
                setattr(flags, key, None)

    _log_provider_action('update_provider_content', 'provider_feature_flags', current_user.id,
                         {k: data[k] for k in data if k in editable
                          or k in ('guard_enabled', 'access_hours_enabled', 'guard_keywords', 'access_hours_days')})
    db.session.commit()
    return jsonify({'status': 'success'})


# ── CLOZE-Guard: escalation events (provider-scoped) ──────────

@provider_bp.route("/api/provider/escalation-events", methods=['GET'])
@role_required('provider')
def get_provider_escalation_events():
    """Provider reads escalation events for their own patients."""
    query = EscalationEvent.query.filter_by(provider_id=current_user.id)
    status_filter = request.args.get('status')
    if status_filter:
        query = query.filter_by(status=status_filter)
    events = query.order_by(
        db.case(
            (EscalationEvent.severity == 'critical', 0),
            (EscalationEvent.severity == 'warning', 1),
            else_=2,
        ),
        EscalationEvent.created_at.desc(),
    ).all()
    return jsonify([e.to_dict() for e in events])


@provider_bp.route("/api/provider/escalation-events/<int:event_id>/acknowledge", methods=['POST'])
@role_required('provider')
def acknowledge_provider_escalation(event_id):
    """Provider acknowledges/resolves an event for one of their own patients."""
    event = EscalationEvent.query.get_or_404(event_id)
    if event.provider_id != current_user.id:
        abort(403)
    data = request.json or {}
    new_status = data.get('status', 'acknowledged')
    event.status = new_status
    if new_status == 'acknowledged':
        event.acknowledged_by = current_user.id
        event.acknowledged_at = time.time()
    _log_provider_action('escalation_acknowledged', 'escalation_event', event_id, {'status': new_status})
    db.session.commit()
    return jsonify({'status': 'success'})


# ── Provider prompt management ────────────────────────────────

@provider_bp.route("/api/provider/prompts", methods=['GET'])
@role_required('provider')
def get_provider_prompts():
    """Get prompts created by this provider."""
    prompts = SystemPrompt.query.filter_by(created_by=current_user.id).all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'content': p.content,
        'visible': p.visible,
        'created_at': p.created_at,
    } for p in prompts])


@provider_bp.route("/api/provider/prompts", methods=['POST'])
@role_required('provider')
def create_provider_prompt():
    """Provider creates a custom system prompt."""
    if not get_effective_setting('allow_custom_prompts', current_user.id, True):
        return jsonify({'error': 'Custom prompts are not enabled for your account'}), 403

    data = request.json or {}
    name = data.get('name', '').strip()
    content = data.get('content', '').strip()
    if not name:
        return jsonify({'error': 'Prompt name is required'}), 400

    prompt = SystemPrompt(
        name=name,
        content=content,
        created_by=current_user.id,
        visible=True,
    )
    db.session.add(prompt)
    _log_provider_action('prompt_created', 'system_prompt', details={'name': name})
    db.session.commit()
    return jsonify({'id': prompt.id, 'name': prompt.name}), 201


@provider_bp.route("/api/provider/prompts/<int:prompt_id>", methods=['PUT'])
@role_required('provider')
def update_provider_prompt(prompt_id):
    """Provider edits a prompt they created."""
    prompt = SystemPrompt.query.get_or_404(prompt_id)
    if prompt.created_by != current_user.id:
        abort(403)

    data = request.json or {}
    if 'name' in data:
        prompt.name = data['name'].strip()
    if 'content' in data:
        prompt.content = data['content'].strip()
    _log_provider_action('prompt_updated', 'system_prompt', prompt_id)
    db.session.commit()
    return jsonify({'status': 'success'})


@provider_bp.route("/api/provider/prompts/<int:prompt_id>", methods=['DELETE'])
@role_required('provider')
def delete_provider_prompt(prompt_id):
    """Provider soft-deletes a prompt they created."""
    prompt = SystemPrompt.query.get_or_404(prompt_id)
    if prompt.created_by != current_user.id:
        abort(403)

    prompt.visible = False
    _log_provider_action('prompt_deleted', 'system_prompt', prompt_id)
    db.session.commit()
    return jsonify({'status': 'success'})


# ── Study Flows ───────────────────────────────────────────────

@provider_bp.route("/provider/study-design")
@role_required('provider')
def study_design_page():
    return render_template("study_design.html")


@provider_bp.route("/api/provider/flows", methods=['GET'])
@role_required('provider')
def get_flows():
    """Get all flows for the current provider. Auto-creates 'Always Available' if none exist."""
    flows = StudyFlow.query.filter_by(provider_id=current_user.id).all()
    if not flows:
        default_flow = StudyFlow(
            provider_id=current_user.id,
            name='Always Available',
            flow_type='always',
        )
        db.session.add(default_flow)
        db.session.flush()
        phase = FlowPhase(flow_id=default_flow.id, name='Always Available',
                          start_day=0, end_day=None, order_index=0)
        db.session.add(phase)
        db.session.commit()
        flows = [default_flow]
    return jsonify([f.to_dict() for f in flows])


@provider_bp.route("/api/provider/flows", methods=['POST'])
@role_required('provider')
def create_flow():
    """Create a new study flow."""
    data = request.json or {}
    name = data.get('name', '').strip()
    flow_type = data.get('flow_type', '')

    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if flow_type not in ('always', 'phased', 'recurring'):
        return jsonify({'error': 'flow_type must be always, phased, or recurring'}), 400

    flow = StudyFlow(
        provider_id=current_user.id,
        name=name,
        flow_type=flow_type,
        cadence_days=data.get('cadence_days'),
        cycle_count=data.get('cycle_count'),
        report_config=json.dumps(data.get('report_config')) if data.get('report_config') else None,
    )
    db.session.add(flow)
    db.session.flush()

    # For 'always' and 'recurring', auto-create a default phase
    if flow_type == 'always':
        phase = FlowPhase(flow_id=flow.id, name='Always Available', start_day=0, end_day=None, order_index=0)
        db.session.add(phase)
    elif flow_type == 'recurring':
        phase = FlowPhase(flow_id=flow.id, name='Each Cycle', start_day=0,
                          end_day=data.get('cadence_days', 7), order_index=0)
        db.session.add(phase)

    _log_provider_action('flow_created', 'study_flow', flow.id, {'name': name, 'type': flow_type})
    db.session.commit()
    return jsonify(flow.to_dict()), 201


@provider_bp.route("/api/provider/flows/<int:flow_id>", methods=['GET'])
@role_required('provider')
def get_flow(flow_id):
    """Get a single flow with full detail."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)

    result = flow.to_dict()
    result['enrollments'] = [e.to_dict() for e in flow.enrollments]
    return jsonify(result)


@provider_bp.route("/api/provider/flows/<int:flow_id>", methods=['PUT'])
@role_required('provider')
def update_flow(flow_id):
    """Update flow metadata."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    if 'name' in data:
        flow.name = data['name'].strip()
    if 'cadence_days' in data:
        flow.cadence_days = data['cadence_days']
    if 'cycle_count' in data:
        flow.cycle_count = data['cycle_count']
    if 'report_config' in data:
        flow.report_config = json.dumps(data['report_config']) if data['report_config'] else None

    db.session.commit()
    return jsonify(flow.to_dict())


@provider_bp.route("/api/provider/flows/<int:flow_id>", methods=['DELETE'])
@role_required('provider')
def delete_flow(flow_id):
    """Delete a flow (only if no patients are enrolled)."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)
    # Deletion stays blocked once anyone has ever been enrolled, withdrawn
    # participants included. Their windows carry a flow_id FK to this row and
    # their reports resolve through the enrollment, so deleting the flow would
    # orphan both. Withdrawing everyone retires a flow without destroying data.
    if flow.enrollments:
        if any(e.is_active for e in flow.enrollments):
            return jsonify({'error': 'Cannot delete a flow with enrolled patients'}), 400
        return jsonify({'error': 'Cannot delete a flow with withdrawn participants — '
                                 'their conversations and reports are still linked to it'}), 400

    _log_provider_action('flow_deleted', 'study_flow', flow_id, {'name': flow.name})
    db.session.delete(flow)
    db.session.commit()
    return jsonify({'status': 'success'})


# ── Flow Phases ───────────────────────────────────────────────

@provider_bp.route("/api/provider/flows/<int:flow_id>/phases", methods=['POST'])
@role_required('provider')
def create_phase(flow_id):
    """Add a phase to a flow."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    max_order = max([p.order_index for p in flow.phases], default=-1)

    phase = FlowPhase(
        flow_id=flow_id,
        name=data.get('name', 'New Phase').strip(),
        start_day=data.get('start_day', 0),
        end_day=data.get('end_day'),
        order_index=max_order + 1,
    )
    db.session.add(phase)
    db.session.commit()
    return jsonify(phase.to_dict()), 201


@provider_bp.route("/api/provider/phases/<int:phase_id>", methods=['PUT'])
@role_required('provider')
def update_phase(phase_id):
    """Update a phase."""
    phase = FlowPhase.query.get_or_404(phase_id)
    if phase.flow.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    if 'name' in data:
        phase.name = data['name'].strip()
    if 'start_day' in data:
        phase.start_day = data['start_day']
    if 'end_day' in data:
        phase.end_day = data['end_day']
    if 'order_index' in data:
        phase.order_index = data['order_index']

    db.session.commit()
    return jsonify(phase.to_dict())


@provider_bp.route("/api/provider/phases/<int:phase_id>", methods=['DELETE'])
@role_required('provider')
def delete_phase(phase_id):
    """Delete a phase and its chats."""
    phase = FlowPhase.query.get_or_404(phase_id)
    if phase.flow.provider_id != current_user.id:
        abort(403)

    db.session.delete(phase)
    db.session.commit()
    return jsonify({'status': 'success'})


# ── Flow Chats ────────────────────────────────────────────────

@provider_bp.route("/api/provider/phases/<int:phase_id>/chats", methods=['POST'])
@role_required('provider')
def create_flow_chat(phase_id):
    """Add a chat to a phase."""
    phase = FlowPhase.query.get_or_404(phase_id)
    if phase.flow.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    max_order = max([c.order_index for c in phase.chats], default=-1)

    chat = FlowChat(
        phase_id=phase_id,
        title=data.get('title', 'New Chat').strip(),
        purpose=data.get('purpose'),
        model_id=data['model_id'],
        system_prompt_id=data.get('system_prompt_id'),
        custom_system_prompt=data.get('custom_system_prompt'),
        max_messages=data.get('max_messages'),
        order_index=max_order + 1,
    )
    db.session.add(chat)
    db.session.flush()

    # phase.chats was loaded above for max_order and won't contain the new row
    # (we set phase_id directly rather than going through the backref), so drop
    # it — the backfill re-reads the collection when generating a fresh window.
    db.session.expire(phase, ['chats'])

    # An always-available flow can be enrolled into before it has any chats;
    # push this one out to anyone already on the roster.
    backfilled = _backfill_chat_to_enrollments(phase.flow, phase, chat)

    db.session.commit()
    result = chat.to_dict()
    result['backfilled_enrollments'] = backfilled
    return jsonify(result), 201


@provider_bp.route("/api/provider/chats/<int:chat_id>", methods=['PUT'])
@role_required('provider')
def update_flow_chat(chat_id):
    """Update a chat."""
    chat = FlowChat.query.get_or_404(chat_id)
    if chat.phase.flow.provider_id != current_user.id:
        abort(403)

    data = request.json or {}
    for key in ('title', 'purpose', 'model_id', 'system_prompt_id',
                'custom_system_prompt', 'max_messages', 'order_index'):
        if key in data:
            setattr(chat, key, data[key])

    db.session.commit()
    return jsonify(chat.to_dict())


@provider_bp.route("/api/provider/chats/<int:chat_id>", methods=['DELETE'])
@role_required('provider')
def delete_flow_chat(chat_id):
    """Delete a chat from a phase."""
    chat = FlowChat.query.get_or_404(chat_id)
    if chat.phase.flow.provider_id != current_user.id:
        abort(403)

    db.session.delete(chat)
    db.session.commit()
    return jsonify({'status': 'success'})


# ── Enrollment ────────────────────────────────────────────────

DAY_SECONDS = 86400


@provider_bp.route("/api/provider/flows/<int:flow_id>/enroll", methods=['POST'])
@role_required('provider')
def enroll_patients(flow_id):
    """Enroll patients in a flow. Generates ChatWindows and ChatTemplates."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)

    # Always-available flows may be enrolled into before any chats exist — the
    # roster is built first and chats are added later, at which point
    # create_flow_chat backfills them into the enrolled participants' windows.
    # Phased and recurring flows still require chats up front, because their
    # windows are dated off the enrollment moment and generated from the chats
    # that exist at that instant.
    if flow.flow_type != 'always' and (not flow.phases or not any(p.chats for p in flow.phases)):
        return jsonify({'error': 'Flow must have at least one phase with chats before enrolling'}), 400

    data = request.json or {}
    patient_ids = data.get('patient_ids', [])
    if not patient_ids:
        return jsonify({'error': 'No patients specified'}), 400

    enrolled = []
    reactivated = []
    for pid in patient_ids:
        if not current_user.can_access_patient(pid):
            continue

        enrollment_time = time.time()
        existing = FlowEnrollment.query.filter_by(flow_id=flow_id, patient_id=pid).first()
        if existing is not None:
            if existing.is_active:
                continue
            # Re-enrolling someone previously withdrawn reuses the row. The
            # unique constraint forbids a second one anyway, and holding the id
            # stable keeps any saved report-v2 'enrollment' scope pointing at
            # real data. The withdrawal itself survives in the audit log.
            existing.status = FlowEnrollment.STATUS_ACTIVE
            existing.withdrawn_at = None
            existing.enrolled_at = enrollment_time
            reactivated.append(pid)
        else:
            db.session.add(FlowEnrollment(
                flow_id=flow_id, patient_id=pid, enrolled_at=enrollment_time,
                status=FlowEnrollment.STATUS_ACTIVE,
            ))

        _generate_windows_for_enrollment(flow, pid, enrollment_time)
        enrolled.append(pid)

    _log_provider_action('patients_enrolled', 'study_flow', flow_id,
                         {'patient_ids': enrolled, 'count': len(enrolled),
                          'reactivated': reactivated})
    db.session.commit()
    return jsonify({'status': 'success', 'enrolled': len(enrolled)})


def _generate_windows_for_enrollment(flow, patient_id, enrollment_time):
    """Generate ChatWindows and ChatTemplates for a patient enrollment."""
    if flow.flow_type == 'always':
        for phase in flow.phases:
            _create_window_from_phase(flow, phase, patient_id,
                                     start=enrollment_time,
                                     end=enrollment_time + (365 * DAY_SECONDS),
                                     phase_label=None)

    elif flow.flow_type == 'phased':
        for phase in flow.phases:
            start = enrollment_time + (phase.start_day * DAY_SECONDS)
            end = enrollment_time + (phase.end_day * DAY_SECONDS) if phase.end_day else start + (365 * DAY_SECONDS)
            _create_window_from_phase(flow, phase, patient_id, start=start, end=end,
                                     phase_label=phase.name)

    elif flow.flow_type == 'recurring':
        cadence = flow.cadence_days or 7
        cycles = flow.cycle_count or 1
        phase = flow.phases[0] if flow.phases else None
        if not phase:
            return
        for cycle in range(cycles):
            start = enrollment_time + (cycle * cadence * DAY_SECONDS)
            end = enrollment_time + ((cycle + 1) * cadence * DAY_SECONDS)
            _create_window_from_phase(flow, phase, patient_id, start=start, end=end,
                                     title_suffix=f" - Cycle {cycle + 1}",
                                     phase_label=f"Cycle {cycle + 1} of {cycles}")


def _create_window_from_phase(flow, phase, patient_id, start, end, title_suffix='', phase_label=None):
    """Create a ChatWindow with ChatTemplates from a FlowPhase."""
    window = ChatWindow(
        patient_id=patient_id,
        provider_id=flow.provider_id,
        title=phase.name + title_suffix,
        start_date=start,
        end_date=end,
        report_config=flow.report_config,
        flow_name=flow.name,
        flow_id=flow.id,
        phase_id=phase.id,
        phase_label=phase_label,
    )
    db.session.add(window)
    db.session.flush()

    for chat in phase.chats:
        _add_template_to_window(window, chat)
    return window


def _add_template_to_window(window, chat):
    """Materialise a FlowChat as a ChatTemplate inside an existing window."""
    template = ChatTemplate(
        window_id=window.id,
        title=chat.title,
        purpose=chat.purpose,
        model_id=chat.model_id,
        system_prompt_id=chat.system_prompt_id,
        custom_system_prompt=chat.custom_system_prompt,
        max_messages=chat.max_messages,
        order_index=chat.order_index,
    )
    db.session.add(template)
    return template


def _backfill_chat_to_enrollments(flow, phase, chat):
    """Push a newly-added chat out to participants already enrolled.

    Only always-available flows backfill. Their windows are open-ended, so a
    chat added later is still reachable by the participant. Phased and
    recurring windows are pinned to dates computed at enrollment and may
    already have closed, so injecting a chat into them would rewrite the
    historical record rather than extend an open one.

    Returns the number of participants whose windows were updated.
    """
    if flow.flow_type != 'always':
        return 0

    enrollments = FlowEnrollment.query.filter(
        FlowEnrollment.flow_id == flow.id,
        FlowEnrollment.active_filter(),
    ).all()

    touched = 0
    for enrollment in enrollments:
        window = ChatWindow.query.filter_by(
            flow_id=flow.id,
            phase_id=phase.id,
            patient_id=enrollment.patient_id,
            visible=True,
        ).first()

        if window is None:
            # Enrolled before this phase existed, so there is no window to
            # extend — generate it now. This also materialises every other
            # chat already on the phase.
            start = enrollment.enrolled_at or time.time()
            _create_window_from_phase(flow, phase, enrollment.patient_id,
                                      start=start,
                                      end=start + (365 * DAY_SECONDS),
                                      phase_label=None)
        else:
            _add_template_to_window(window, chat)
        touched += 1

    return touched


@provider_bp.route("/api/provider/flows/<int:flow_id>/enroll/<int:patient_id>", methods=['DELETE'])
@role_required('provider')
def unenroll_patient(flow_id, patient_id):
    """Withdraw a participant from a flow.

    Withdrawal is a soft delete. The enrollment row, every conversation, every
    finished window and every report generated from them are left untouched —
    the participant's history is the research record. Only windows that haven't
    finished yet are hidden, which is enough to remove them from the
    participant's view and to make send_message reject further messages.
    """
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)
    if not current_user.can_access_patient(patient_id):
        abort(403)

    enrollment = FlowEnrollment.query.filter_by(
        flow_id=flow_id, patient_id=patient_id
    ).first()
    if enrollment is None or not enrollment.is_active:
        return jsonify({'error': 'Participant is not enrolled in this flow'}), 404

    now = time.time()
    enrollment.status = FlowEnrollment.STATUS_WITHDRAWN
    enrollment.withdrawn_at = now
    hidden = _hide_unfinished_windows(flow, patient_id, now)

    _log_provider_action('patient_unenrolled', 'study_flow', flow_id,
                         {'patient_id': patient_id,
                          'enrollment_id': enrollment.id,
                          'windows_hidden': hidden})
    db.session.commit()
    return jsonify({'status': 'success', 'windows_hidden': hidden})


def _hide_unfinished_windows(flow, patient_id, now):
    """Hide a participant's not-yet-finished windows for one flow.

    Windows whose end_date has already passed are left alone — they and their
    reports are the historical record. Nothing is ever deleted here.

    Legacy windows generated before the flow_id FK existed are matched on
    flow_name instead, mirroring the fallback the report-v2 scope resolver uses.
    """
    windows = ChatWindow.query.filter(
        ChatWindow.patient_id == patient_id,
        ChatWindow.visible.is_(True),
        ChatWindow.end_date >= now,
        or_(ChatWindow.flow_id == flow.id,
            and_(ChatWindow.flow_id.is_(None),
                 ChatWindow.flow_name == flow.name)),
    ).all()

    for window in windows:
        window.visible = False
    return len(windows)


@provider_bp.route("/api/provider/flows/<int:flow_id>/enrollments", methods=['GET'])
@role_required('provider')
def get_enrollments(flow_id):
    """Get all enrollments for a flow with progress info."""
    flow = StudyFlow.query.get_or_404(flow_id)
    if flow.provider_id != current_user.id:
        abort(403)

    enrollments = FlowEnrollment.query.filter_by(flow_id=flow_id).all()
    result = []
    for e in enrollments:
        # Count total and completed chats for this patient in this flow's windows
        windows = ChatWindow.query.filter_by(
            patient_id=e.patient_id, provider_id=flow.provider_id
        ).all()
        total_chats = 0
        completed_chats = 0
        current_phase = None
        now = time.time()
        for w in windows:
            templates = w.templates.all()
            total_chats += len(templates)
            for t in templates:
                conv = Conversation.query.filter_by(
                    user_id=e.patient_id, window_id=w.id, template_id=t.id
                ).first()
                if conv and conv.messages.count() > 0:
                    completed_chats += 1
            status = w.compute_status(now)
            if status == 'active':
                current_phase = w.title

        result.append({
            **e.to_dict(),
            'total_chats': total_chats,
            'completed_chats': completed_chats,
            'current_phase': current_phase,
        })

    return jsonify(result)
