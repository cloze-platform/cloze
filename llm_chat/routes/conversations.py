import json
import time
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, abort, redirect, current_app
from flask_login import login_required, current_user
from ..extensions import db
from ..models import (
    User, ProviderPatient, ProviderSettings, SystemPrompt,
    Conversation, Model, Message, SavedSelection, ChatWindow, ChatTemplate
)
from ..services.llm_interface import LLMInterface
from ..models import ProviderFeatureFlags
from ..utils.settings_resolution import get_effective_setting, get_provider_id_for_patient
from ..utils.access_hours import within_access_window

conv_bp = Blueprint("conversations", __name__, url_prefix="")

# -------- User dashboards / pages

@conv_bp.route("/dashboard")
@login_required
def user_dashboard():
    if current_user.is_admin():
        return render_template("admin_dashboard.html")
    elif current_user.is_provider():
        return render_template("provider_dashboard.html")
    # For patients, show the new chat windows interface
    return render_template("user_dashboard.html")

@conv_bp.route("/chat-windows")
@login_required
def new_conversation():
    if current_user.is_patient():
        return redirect('/dashboard')
    return render_template("user_chat_windows.html")

@conv_bp.route("/my-reports")
@login_required
def patient_reports():
    if current_user.is_patient():
        return redirect('/dashboard')
    return render_template("patient_reports.html")

@conv_bp.route("/api/provider_settings")
@login_required
def get_provider_settings_for_current_user():
    """Provider settings as applied to current patient"""
    if not current_user.is_patient():
        return jsonify(None)

    provider_assignment = ProviderPatient.query.filter_by(patient_id=current_user.id).first()
    if not provider_assignment:
        return jsonify(None)

    settings = (ProviderSettings.query.filter_by(
        provider_id=provider_assignment.provider_id,
        patient_id=current_user.id
    ).first() or ProviderSettings.query.filter_by(
        provider_id=provider_assignment.provider_id,
        patient_id=None
    ).first())

    if not settings:
        return jsonify(None)

    return jsonify({
        'allowed_models': json.loads(settings.allowed_models or '[]'),
        'system_prompt_id': settings.system_prompt_id,
        'time_window_start': settings.time_window_start,
        'time_window_end': settings.time_window_end,
        'max_messages_per_day': settings.max_messages_per_day,
        'custom_instructions': settings.custom_instructions
    })

@conv_bp.route("/api/access-window")
@login_required
def get_access_window():
    """Current participant's access-hours status — drives the 'snoozing' takeover."""
    if not current_user.is_patient():
        return jsonify({'enabled': False})

    provider_id = get_provider_id_for_patient(current_user.id)
    if not get_effective_setting('access_hours_enabled', provider_id, False):
        return jsonify({'enabled': False})

    start = get_effective_setting('access_hours_start', provider_id)
    end = get_effective_setting('access_hours_end', provider_id)
    if not start or not end:
        return jsonify({'enabled': False})

    tz = get_effective_setting('access_hours_timezone', provider_id, 'America/New_York')
    days_raw = get_effective_setting('access_hours_days', provider_id)
    try:
        days = json.loads(days_raw) if days_raw else None
    except (TypeError, ValueError):
        days = None

    from ..utils.access_hours import window_status
    status = window_status(start, end, tz, days)
    status['enabled'] = True
    return jsonify(status)


@conv_bp.route("/conversation/<int:conversation_id>")
@login_required
def view_conversation(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if not current_user.can_access_patient(conversation.user_id):
        abort(403)

    # Patients use the unified dashboard
    if current_user.is_patient():
        return redirect('/dashboard?conversation=' + str(conversation_id))

    can_send_messages = False
    is_provider = current_user.is_provider()
    window_status = None
    has_report = False
    window_id = None

    # Check if conversation belongs to an expired window
    if conversation.window_id:
        window = ChatWindow.query.get(conversation.window_id)
        if window:
            window_status = window.compute_status()
            window_id = window.id
            from ..models import Report
            has_report = Report.query.filter_by(window_id=window.id).first() is not None

    return render_template("conversation.html", conversation_id=conversation_id, can_send_messages=can_send_messages, is_provider=is_provider, window_status=window_status, patient_id=conversation.user_id, has_report=has_report, window_id=window_id)

@conv_bp.route("/api/conversation/<int:conversation_id>")
@login_required
def get_conversation_data(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if not current_user.can_access_patient(conversation.user_id):
        abort(403)

    messages = conversation.messages.order_by(Message.timestamp).all()

    # Get window info if conversation belongs to a window
    window_end_date = None
    window_id = None
    window_status = None
    if conversation.window_id:
        window = ChatWindow.query.get(conversation.window_id)
        if window:
            window_end_date = window.end_date
            window_id = window.id
            window_status = window.compute_status()

    # Turn limit info
    turn_info = {}
    if current_user.is_patient():
        provider_id = get_provider_id_for_patient(conversation.user_id)
        mt = get_effective_setting('max_turns_per_conversation', provider_id)
        if mt:
            used = sum(1 for m in messages if m.role == 'user')
            turn_info = {
                'max_turns': mt,
                'turns_used': used,
                'turns_remaining': max(0, mt - used),
                'turn_limit_reached': used >= mt,
            }

    return jsonify({
        'id': conversation.id,
        'title': conversation.title or 'New Conversation',
        'model': {
            'id': conversation.model.id,
            'name': conversation.model.name
        },
        'system_prompt': None if not conversation.system_prompt_id else {
            'id': conversation.system_prompt_id,
            'name': SystemPrompt.query.get(conversation.system_prompt_id).name if conversation.system_prompt_id else None
        },
        'window_end_date': window_end_date,
        'window_status': window_status,
        'window_id': window_id,
        'consent_provided': conversation.consent_provided,
        'messages': [m.to_dict() for m in messages],
        **turn_info,
    })

@conv_bp.route("/api/conversation/<int:conversation_id>/title", methods=["PUT"])
@login_required
def update_conversation_title(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if conversation.user_id != current_user.id:
        abort(403)
    data = request.json or {}
    conversation.title = data.get('title', '').strip()[:200]
    conversation.updated_at = time.time()
    db.session.commit()
    return jsonify({'status': 'success', 'title': conversation.title})

@conv_bp.route("/api/conversation/<int:conversation_id>/consent", methods=["POST"])
@login_required
def mark_consent_provided(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    if conversation.user_id != current_user.id:
        abort(403)
    conversation.consent_provided = True
    db.session.commit()
    return jsonify({'status': 'success', 'consent_provided': True})

@conv_bp.route("/api/conversations")
@login_required
def get_conversations():
    conversations = current_user.conversations.order_by(Conversation.updated_at.desc()).all()

    payload = []
    now = time.time()
    started_template_ids = set()

    for c in conversations:
        msgs = c.messages.order_by(Message.timestamp).all()

        if c.template_id:
            started_template_ids.add(c.template_id)

        window_end_date = None
        window_start_date = None
        window_title = None
        window_description = None
        window_status = None
        is_upcoming = False
        is_active = c.visible

        if c.window_id:
            window = ChatWindow.query.get(c.window_id)
            if window:
                # Skip conversations in hidden windows
                if not window.visible:
                    continue
                window_end_date = window.end_date
                window_start_date = window.start_date
                window_title = window.title
                window_description = window.description
                window_status = window.compute_status(now)
                is_upcoming = window_status == 'scheduled'
                is_active = window_status == 'active'

        if len(msgs) == 0 and not c.visible:
            continue

        payload.append({
            'id': c.id,
            'title': c.title or 'Untitled Conversation',
            'model': c.model.name,
            'created_at': c.created_at,
            'updated_at': c.updated_at,
            'message_count': len(msgs),
            'messages': [m.to_dict() for m in msgs],
            'visible': c.visible,
            'is_active': is_active,
            'is_upcoming': is_upcoming,
            'window_id': c.window_id,
            'window_status': window_status,
            'window_end_date': window_end_date,
            'window_start_date': window_start_date,
            'window_title': window_title,
            'window_description': window_description,
            'template_id': c.template_id
        })

    windows = [
        w for w in ChatWindow.query.filter_by(
            patient_id=current_user.id,
            visible=True
        ).all()
        if w.compute_status(now) in ('scheduled', 'active')
    ]

    for window in windows:
        window_status = window.compute_status(now)
        is_upcoming = window_status == 'scheduled'
        is_current = window_status == 'active'

        templates = ChatTemplate.query.filter_by(
            window_id=window.id,
            visible=True
        ).order_by(ChatTemplate.order_index).all()

        for template in templates:
            if template.id in started_template_ids:
                continue

            title_suffix = " (Not Started)" if is_current else " (Scheduled)"
            payload.append({
                'id': None,
                'title': f"{template.title}{title_suffix}",
                'model': template.model.name if template.model else 'Unknown',
                'created_at': window.created_at,
                'updated_at': window.created_at,
                'message_count': 0,
                'messages': [],
                'visible': True,
                'is_active': is_current,
                'is_upcoming': is_upcoming,
                'window_status': window_status,
                'window_start_date': window.start_date,
                'window_end_date': window.end_date,
                'window_title': window.title,
                'window_description': window.description,
                'template_id': template.id,
                'is_placeholder': True,
                'window_id': window.id
            })

    return jsonify(payload)


@conv_bp.route("/api/conversation/<int:conversation_id>/message", methods=["POST"])
@login_required
def send_message(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)

    # Access check
    if conversation.user_id != current_user.id and not current_user.can_access_patient(conversation.user_id):
        abort(403)

    # Participant chats must come from a chat window: only that path stores the
    # composed system prompt, so a windowless conversation would reach the model
    # without the universal safety layers.
    if current_user.is_patient() and not conversation.window_id:
        return jsonify({'error': 'This conversation is not part of a study chat window'}), 403

    # Check if conversation belongs to an expired window
    if conversation.window_id:
        window = ChatWindow.query.get(conversation.window_id)
        if window:
            status = window.compute_status()
            if not window.visible or status != 'active':
                return jsonify({'error': 'Chat window has expired or is no longer active'}), 403

    # Max turns per conversation enforcement
    max_turns = None
    turns_used = 0
    if current_user.is_patient():
        provider_id = get_provider_id_for_patient(current_user.id)
        max_turns = get_effective_setting('max_turns_per_conversation', provider_id)
        if max_turns:
            turns_used = Message.query.filter_by(
                conversation_id=conversation_id,
                role='user'
            ).count()
            if turns_used >= max_turns:
                return jsonify({
                    'error': f'This conversation has reached its maximum of {max_turns} exchanges.',
                    'turn_limit_reached': True,
                    'max_turns': max_turns,
                }), 403

    # CLOZE-Guard v0: study-wide access-hours restriction (per-provider)
    if current_user.is_patient():
        provider_id = get_provider_id_for_patient(current_user.id)
        if get_effective_setting('access_hours_enabled', provider_id, False):
            start = get_effective_setting('access_hours_start', provider_id)
            end = get_effective_setting('access_hours_end', provider_id)
            tz = get_effective_setting('access_hours_timezone', provider_id, 'America/New_York')
            days_raw = get_effective_setting('access_hours_days', provider_id)
            try:
                days = json.loads(days_raw) if days_raw else None
            except (TypeError, ValueError):
                days = None
            if not within_access_window(start, end, tz, days):
                return jsonify({
                    'error': f'Chat is available {start}–{end} ({tz}).',
                    'outside_access_hours': True,
                }), 403

    # Time window and limits for patients
    if current_user.is_patient():
        provider_assignment = ProviderPatient.query.filter_by(patient_id=current_user.id).first()
        if provider_assignment:
            settings = ProviderSettings.query.filter_by(
                provider_id=provider_assignment.provider_id,
                patient_id=current_user.id
            ).first()
            if settings:
                # Time window check
                if settings.time_window_start and settings.time_window_end:
                    now = datetime.now().strftime('%H:%M')
                    if not (settings.time_window_start <= now <= settings.time_window_end):
                        return jsonify({'error': 'Outside allowed chat hours'}), 403
                # Daily message limit
                if settings.max_messages_per_day:
                    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    today_messages = Message.query.join(Conversation).filter(
                        Conversation.user_id == current_user.id,
                        Message.timestamp >= today_start,
                        Message.role == 'user'
                    ).count()
                    if today_messages >= settings.max_messages_per_day:
                        return jsonify({'error': 'Daily message limit reached'}), 403

    data = request.json or {}

    # Save user message
    user_message = Message(
        conversation_id=conversation_id,
        role='user',
        content=data['message'],
        timestamp=time.time()
    )
    db.session.add(user_message)

    # CLOZE-Guard v0: keyword pre-classifier. Best-effort — must never block chat.
    if current_user.is_patient():
        try:
            from ..services.guard import scan_and_escalate
            scan_and_escalate(current_user, conversation, data['message'])
        except Exception:
            current_app.logger.exception("CLOZE-Guard scan failed")

    # Generate title if first message
    if conversation.messages.count() == 0:
        conversation.generate_title()

    # History (last 20)
    history = [{'role': m.role, 'content': m.content}
               for m in conversation.messages.order_by(Message.timestamp).limit(20)]
    history.append({'role': 'user', 'content': data['message']})

    system_prompt = conversation.system_prompt_content

    # Inject turn-count awareness when approaching the limit
    turns_remaining = None
    if max_turns:
        turns_remaining = max_turns - (turns_used + 1)  # +1 for the message being sent now
        if turns_remaining <= 5:
            turn_notice = (
                f"\n\n---\n\n## Turn Limit Notice\n"
                f"This conversation has {turns_remaining} exchange{'s' if turns_remaining != 1 else ''} remaining "
                f"(out of {max_turns} total). "
            )
            if turns_remaining <= 1:
                turn_notice += (
                    "This is the FINAL exchange. Wrap up the conversation naturally. "
                    "Let the person know you've enjoyed the conversation and that this is "
                    "the last exchange in this session."
                )
            elif turns_remaining <= 3:
                turn_notice += (
                    "The conversation is nearing its end. Begin naturally winding down. "
                    "If there are key takeaways or action items, gently surface them."
                )
            else:
                turn_notice += "Continue the conversation naturally but be aware of the remaining time."
            if system_prompt:
                system_prompt = system_prompt + turn_notice
            else:
                system_prompt = turn_notice

    # Call LLM
    response_text, response_time = LLMInterface.call_llm(conversation.model, history, system_prompt)

    # Save assistant message
    assistant_message = Message(
        conversation_id=conversation_id,
        role='assistant',
        content=response_text,
        timestamp=time.time(),
        response_time=response_time
    )
    db.session.add(assistant_message)

    conversation.updated_at = time.time()
    db.session.commit()

    result = {'response': response_text, 'message_id': assistant_message.id}
    if max_turns:
        result['turns_remaining'] = max(0, turns_remaining)
        result['max_turns'] = max_turns
        result['turn_limit_reached'] = turns_remaining <= 0
    return jsonify(result)

@conv_bp.route("/api/save_selection", methods=["POST"])
@login_required
def save_selection():
    data = request.json or {}
    selection = SavedSelection(
        user_id=current_user.id,
        conversation_id=data['conversation_id'],
        selection_text=data['text'],
        message_ids=json.dumps(data.get('message_ids', [])),
        note=data.get('note')
    )
    db.session.add(selection)
    db.session.commit()
    return jsonify({'status': 'success', 'id': selection.id})

@conv_bp.route("/api/selections")
@login_required
def get_selections():
    # Providers can view a patient's selections
    patient_id = request.args.get('patient_id')
    if patient_id and (current_user.is_provider() or current_user.is_admin()):
        if not current_user.can_access_patient(int(patient_id)):
            abort(403)
        target_user = User.query.get_or_404(int(patient_id))
        selections = target_user.saved_selections.order_by(SavedSelection.created_at.desc()).limit(50).all()
    else:
        selections = current_user.saved_selections.order_by(SavedSelection.created_at.desc()).limit(50).all()
    conversation_titles = {}
    if selections:
        conv_ids = {s.conversation_id for s in selections}
        conversations = Conversation.query.filter(Conversation.id.in_(conv_ids)).all()
        for conv in conversations:
            if conv:
                conversation_titles[conv.id] = (conv.title or f"Conversation {conv.id}").strip() or f"Conversation {conv.id}"

    return jsonify([{
        'id': s.id,
        'text': s.selection_text,
        'note': s.note or conversation_titles.get(s.conversation_id) or f"Conversation {s.conversation_id}",
        'conversation_id': s.conversation_id,
        'created_at': s.created_at
    } for s in selections])

@conv_bp.route("/api/selections/<int:selection_id>", methods=["DELETE"])
@login_required
def delete_selection(selection_id):
    selection = SavedSelection.query.get_or_404(selection_id)
    if selection.user_id != current_user.id:
        abort(403)

    db.session.delete(selection)
    db.session.commit()
    return jsonify({'status': 'deleted', 'id': selection_id})

# -------- Shared APIs: models & system prompts

@conv_bp.route("/api/models")
@login_required
def get_available_models():
    """Get available models based on connectivity and restrictions"""
    models = Model.query.filter_by(visible=True).all()
    available = []

    for model in models:
        model.is_available = model.check_availability()
        model.last_availability_check = time.time()

        if not model.is_available:
            continue

        # Admin-enforced provider-level model allowlist
        check_provider_id = None
        if current_user.is_patient():
            provider_assignment = ProviderPatient.query.filter_by(patient_id=current_user.id).first()
            if provider_assignment:
                check_provider_id = provider_assignment.provider_id
                # Provider-set per-patient restrictions
                settings = ProviderSettings.query.filter_by(
                    provider_id=provider_assignment.provider_id,
                    patient_id=current_user.id
                ).first()
                if settings and settings.allowed_models:
                    allowed = json.loads(settings.allowed_models)
                    if model.id not in allowed:
                        continue
        elif current_user.is_provider():
            check_provider_id = current_user.id

        if check_provider_id:
            flags = ProviderFeatureFlags.query.filter_by(provider_id=check_provider_id).first()
            if flags and flags.allowed_models:
                admin_allowed = json.loads(flags.allowed_models)
                if model.id not in admin_allowed:
                    continue

        available.append({'id': model.id, 'name': model.name, 'provider': model.provider})

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    print(f"Available models: {[m['name'] for m in available]}")
    return jsonify(available)

@conv_bp.route("/api/system_prompts")
@login_required
def get_system_prompts():
    """Get available system prompts (domain-linked) for dropdowns.

    Returns admin-created prompts (visible=True) plus the current
    provider's own prompts (if provider is logged in).
    """
    from sqlalchemy import or_

    def _filter_by_allowed(prompts_list, flags_row, include_own=False):
        """Filter prompts by allowed_prompts. None/empty = no prompts (general only)."""
        if not flags_row:
            return prompts_list  # No flags row = no restrictions
        if flags_row.allowed_prompts:
            allowed_ids = set(json.loads(flags_row.allowed_prompts))
            return [p for p in prompts_list if p.id in allowed_ids
                    or (include_own and p.created_by == current_user.id)]
        # Flags row exists but allowed_prompts is None = none selected = general only
        if include_own:
            return [p for p in prompts_list if p.created_by == current_user.id]
        return []

    if current_user.is_provider():
        prompts = SystemPrompt.query.filter(
            SystemPrompt.visible == True,
            or_(SystemPrompt.created_by == None, SystemPrompt.created_by == current_user.id)
        ).all()
        flags = ProviderFeatureFlags.query.filter_by(provider_id=current_user.id).first()
        prompts = _filter_by_allowed(prompts, flags, include_own=True)
    elif current_user.is_patient():
        prompts = SystemPrompt.query.filter_by(visible=True).all()
        provider_id = get_provider_id_for_patient(current_user.id)
        if provider_id:
            flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first()
            prompts = _filter_by_allowed(prompts, flags)
    else:
        prompts = SystemPrompt.query.filter_by(visible=True).all()

    provider_custom_instructions = None
    if current_user.is_patient():
        provider_assignment = ProviderPatient.query.filter_by(patient_id=current_user.id).first()
        if provider_assignment:
            settings = (ProviderSettings.query.filter_by(
                provider_id=provider_assignment.provider_id,
                patient_id=current_user.id
            ).first() or ProviderSettings.query.filter_by(
                provider_id=provider_assignment.provider_id,
                patient_id=None
            ).first())
            if settings:
                provider_custom_instructions = settings.custom_instructions
                # If provider forced a specific prompt, only return that one
                if settings.system_prompt_id:
                    prompt = SystemPrompt.query.get(settings.system_prompt_id)
                    if prompt:
                        content = prompt.content
                        if provider_custom_instructions:
                            content = f"{content}\n\nProvider Instructions: {provider_custom_instructions.strip()}"
                        return jsonify([{'id': prompt.id, 'name': prompt.name, 'content': content}])

    from prompts.registry import PromptRegistry
    registry = PromptRegistry.instance()

    result = []
    for p in prompts:
        entry = {
            'id': p.id,
            'name': p.name,
            'content': p.content,
            'domain_prompt_id': p.domain_prompt_id,
        }
        # Enrich with domain metadata if linked
        if p.domain_prompt_id:
            domain = registry.get_domain_prompt(p.domain_prompt_id)
            if domain:
                entry['description'] = domain.description
                entry['tags'] = domain.tags
        if provider_custom_instructions:
            entry['content'] = f"{entry['content']}\n\nProvider Instructions: {provider_custom_instructions.strip()}"
        result.append(entry)

    return jsonify(result)


@conv_bp.route("/api/user/settings-flags")
@login_required
def get_user_settings_flags():
    """Feature flags relevant to the current user's role."""
    provider_id = None
    if current_user.is_patient():
        provider_id = get_provider_id_for_patient(current_user.id)
    elif current_user.is_provider():
        provider_id = current_user.id

    flags = {
        'users_can_save_selections': get_effective_setting('users_can_save_selections', provider_id, True),
        'require_safety_plan': get_effective_setting('require_safety_plan', provider_id, True),
        'enable_nlp_report': get_effective_setting('enable_nlp_report', provider_id, True),
    }
    if current_user.is_provider():
        flags['providers_can_set_custom_prompts'] = get_effective_setting('allow_custom_prompts', current_user.id, True)
    return jsonify(flags)


@conv_bp.route("/api/safety-disclaimer")
@login_required
def get_safety_disclaimer():
    """Get the safety disclaimer HTML for the current patient's provider."""
    provider_id = None
    if current_user.is_patient():
        provider_id = get_provider_id_for_patient(current_user.id)
    elif current_user.is_provider():
        provider_id = current_user.id

    if provider_id:
        flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first()
        if flags and flags.safety_disclaimer_text:
            raw = flags.safety_disclaimer_text
            # Check if it's JSON blocks (new format) or raw HTML (legacy)
            try:
                blocks = json.loads(raw)
                if isinstance(blocks, list):
                    html = _compile_disclaimer_blocks(blocks)
                    return jsonify({'text': html, 'custom': True})
            except (json.JSONDecodeError, TypeError):
                pass
            # Legacy raw HTML
            return jsonify({'text': raw, 'custom': True})

    return jsonify({'text': None, 'custom': False})


def _compile_disclaimer_blocks(blocks):
    """Compile disclaimer blocks to HTML (server-side rendering)."""
    import re

    def boldify(text):
        escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)

    parts = []
    for block in blocks:
        btype = block.get('type', 'text')
        content = block.get('content', '')

        if btype == 'text':
            parts.append(f'<p class="mb-4 text-sm leading-relaxed text-stone-700">{boldify(content)}</p>')
        elif btype == 'warning':
            title = block.get('title', 'Warning')
            lines = content.split('\n')
            list_items = [l for l in lines if l.strip().startswith('-')]
            plain = [l for l in lines if not l.strip().startswith('-')]
            html = '<div class="rounded-lg border-l-4 border-amber-400 bg-amber-50 p-4 my-4">'
            html += f'<h3 class="text-sm font-semibold text-amber-800 mb-2">{boldify(title)}</h3>'
            if plain:
                html += f'<p class="text-sm text-amber-900 mb-2">{boldify(" ".join(plain))}</p>'
            if list_items:
                html += '<ul class="list-disc pl-5 text-sm text-amber-900 space-y-1">'
                for li in list_items:
                    html += f'<li>{boldify(li.strip().lstrip("- "))}</li>'
                html += '</ul>'
            html += '</div>'
            parts.append(html)
        elif btype == 'alert':
            title = block.get('title', 'Alert')
            html = '<div class="rounded-lg border-l-4 border-red-500 bg-red-50 p-4 my-4">'
            html += f'<h3 class="text-sm font-semibold text-red-900 mb-2">{boldify(title)}</h3>'
            html += f'<p class="text-sm text-red-900">{boldify(content)}</p>'
            html += '</div>'
            parts.append(html)
        elif btype == 'checkbox':
            html = '<div class="mt-5 pt-5 border-t border-stone-200">'
            html += '<label class="flex items-start gap-2.5 cursor-pointer select-none">'
            html += '<input type="checkbox" id="safetyAcknowledge" class="mt-0.5 h-4 w-4 cursor-pointer rounded border-stone-300 text-cloze-indigo focus:ring-cloze-indigo">'
            html += f'<span class="text-sm text-stone-700">{boldify(content)}</span>'
            html += '</label></div>'
            parts.append(html)

    return '\n'.join(parts)


@conv_bp.route("/api/prompts/domains")
@login_required
def get_domain_prompts():
    """Get all domain prompts with metadata for the provider UI."""
    from prompts.registry import PromptRegistry
    registry = PromptRegistry.instance()

    result = []
    for domain in registry.list_domain_prompts():
        # Find the corresponding SystemPrompt row (if seeded)
        sp = SystemPrompt.query.filter_by(domain_prompt_id=domain.id).first()
        result.append({
            'id': domain.id,
            'name': domain.name,
            'description': domain.description,
            'tags': domain.tags,
            'system_prompt_id': sp.id if sp else None,
        })

    return jsonify(result)
