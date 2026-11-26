import time
from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from ..extensions import db
from ..models import SafetyPlan, User, ProviderPatient
from ..utils.settings_resolution import get_effective_setting, get_provider_id_for_patient

safety_bp = Blueprint("safety_plan", __name__, url_prefix="/api/safety-plan")


# ── Patient endpoints ──────────────────────────────────────────

# The participant's sections: the fields each entry may have, and which are
# 1-5 ratings (the prompt reads them). Anything else is dropped. Bad shapes are
# refused, because these lists are rendered on every participant page (Get
# help now) and fed to the prompt.
PATIENT_SECTIONS = {
    'warning_signs': {'text': ('sign', 'context'), 'ratings': ('severity',), 'required': 'sign'},
    'coping_strategies': {'text': ('strategy', 'context', 'patient_language'), 'ratings': ('effectiveness',),
                          'required': 'strategy'},
    'support_network': {'text': ('person', 'relationship', 'contact_preference'), 'ratings': ('comfort_level',),
                        'required': 'person'},
    'reasons_for_living': {'text': ('reason', 'context'), 'ratings': (), 'required': 'reason'},
}
MAX_ENTRIES, MAX_TEXT = 50, 500


def _clean_section(name, items):
    """The section as a list of clean entries. Raises ValueError for a bad shape."""
    spec = PATIENT_SECTIONS[name]
    if not isinstance(items, list) or len(items) > MAX_ENTRIES:
        raise ValueError(f'{name} must be a list of up to {MAX_ENTRIES} entries')
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f'Each {name} entry must be an object')
        entry = {}
        for field in spec['text']:
            value = item.get(field, '')
            if value is None:
                value = ''
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise ValueError(f'{name}.{field} must be text of up to {MAX_TEXT} characters')
            entry[field] = value.strip()
        for field in spec['ratings']:
            value = item.get(field, 3)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f'{name}.{field} must be a whole number from 1 to 5')
            entry[field] = value
        if entry[spec['required']]:
            cleaned.append(entry)
    return cleaned

@safety_bp.route("/", methods=["GET"])
@login_required
def get_my_plan():
    """Get current patient's active plan + any pending draft."""
    if not current_user.is_patient():
        abort(403)

    active = SafetyPlan.get_active_plan(current_user.id)
    pending = SafetyPlan.get_pending_plan(current_user.id)
    draft = SafetyPlan.query.filter_by(
        patient_id=current_user.id, status='draft'
    ).first()

    result = {
        'active': active.to_dict(for_patient=True) if active else None,
        'pending': pending.to_dict(for_patient=True) if pending else None,
        'draft': draft.to_dict(for_patient=True) if draft else None,
    }
    return jsonify(result)


@safety_bp.route("/patient-sections", methods=["PUT"])
@login_required
def update_patient_sections():
    """Patient submits/updates their sections."""
    if not current_user.is_patient():
        abort(403)

    data = request.json or {}
    try:
        sections = {name: _clean_section(name, data[name]) for name in PATIENT_SECTIONS if name in data}
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    # Find the plan to update: draft first, then create a new pending version from active
    plan = SafetyPlan.query.filter_by(
        patient_id=current_user.id, status='draft'
    ).first()

    if not plan:
        # Check for existing pending
        plan = SafetyPlan.get_pending_plan(current_user.id)

    if not plan:
        # Create a new pending version from active
        active = SafetyPlan.get_active_plan(current_user.id)
        if not active:
            return jsonify({'error': 'No safety plan exists yet. Your provider must create one first.'}), 400

        plan = SafetyPlan(
            patient_id=current_user.id,
            status='pending_review',
            version=active.version + 1,
            # Copy provider sections from active
            anti_patterns=active.anti_patterns,
            care_team=active.care_team,
            emergency_plan=active.emergency_plan,
            provider_notes=active.provider_notes,
        )
        db.session.add(plan)

    # Update patient sections
    for name, entries in sections.items():
        getattr(plan, f'set_{name}')(entries)

    # If this was a draft and patient sections are now complete, move to
    # pending_review. "submit": false saves a draft without sending it (the
    # new participant page's Save for later); it defaults to sending, as before.
    if plan.status == 'draft' and plan.is_complete() and data.get('submit', True) is not False:
        plan.status = 'pending_review'

    plan.updated_at = time.time()
    db.session.commit()

    return jsonify(plan.to_dict(for_patient=True))


@safety_bp.route("/anti-pattern", methods=["POST"])
@login_required
def add_patient_anti_pattern():
    """Patient adds an anti-pattern (source='patient', visible=true)."""
    if not current_user.is_patient():
        abort(403)

    if not get_effective_setting('allow_patient_anti_patterns', get_provider_id_for_patient(current_user.id), True):
        return jsonify({'error': 'Adding anti-patterns is currently disabled by your administrator.'}), 403

    data = request.json or {}
    pattern, reason = data.get('pattern'), data.get('reason') or ''
    if not isinstance(pattern, str) or not pattern.strip():
        return jsonify({'error': 'Pattern text is required'}), 400
    if not isinstance(reason, str) or len(pattern) > MAX_TEXT or len(reason) > MAX_TEXT:
        return jsonify({'error': f'Pattern and reason must be text of up to {MAX_TEXT} characters'}), 400

    # Find the editable plan
    plan = SafetyPlan.query.filter_by(
        patient_id=current_user.id, status='draft'
    ).first()
    if not plan:
        plan = SafetyPlan.get_pending_plan(current_user.id)
    if not plan:
        active = SafetyPlan.get_active_plan(current_user.id)
        if not active:
            return jsonify({'error': 'No safety plan exists yet.'}), 400
        # Create new pending version
        plan = SafetyPlan(
            patient_id=current_user.id,
            status='pending_review',
            version=active.version + 1,
            warning_signs=active.warning_signs,
            coping_strategies=active.coping_strategies,
            support_network=active.support_network,
            reasons_for_living=active.reasons_for_living,
            anti_patterns=active.anti_patterns,
            care_team=active.care_team,
            emergency_plan=active.emergency_plan,
            provider_notes=active.provider_notes,
        )
        db.session.add(plan)

    anti_patterns = plan.get_anti_patterns()
    anti_patterns.append({
        'pattern': pattern.strip(),
        'reason': reason.strip(),
        'severity': 2,  # moderate default
        'source': 'patient',
        'visible_to_patient': True,
    })
    plan.set_anti_patterns(anti_patterns)
    plan.updated_at = time.time()
    db.session.commit()

    return jsonify(plan.to_dict(for_patient=True))


# ── Provider endpoints ─────────────────────────────────────────

@safety_bp.route("/patient/<int:patient_id>", methods=["GET"])
@login_required
def get_patient_plan(patient_id):
    """Get a patient's plan (active + pending) — provider view."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)
    if not current_user.can_access_patient(patient_id):
        abort(403)

    active = SafetyPlan.get_active_plan(patient_id)
    pending = SafetyPlan.get_pending_plan(patient_id)
    draft = SafetyPlan.query.filter_by(patient_id=patient_id, status='draft').first()

    result = {
        'active': active.to_dict() if active else None,
        'pending': pending.to_dict() if pending else None,
        'draft': draft.to_dict() if draft else None,
    }
    return jsonify(result)


@safety_bp.route("/patient/<int:patient_id>", methods=["POST"])
@login_required
def create_patient_plan(patient_id):
    """Create initial safety plan for a patient (provider sections)."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)
    if not current_user.can_access_patient(patient_id):
        abort(403)

    # Don't create if there's already an active or draft plan
    existing = SafetyPlan.query.filter(
        SafetyPlan.patient_id == patient_id,
        SafetyPlan.status.in_(['active', 'draft', 'pending_review'])
    ).first()
    if existing:
        return jsonify({'error': 'A safety plan already exists for this patient.'}), 409

    data = request.json or {}

    # Auto-populate care team from ProviderPatient relationship
    care_team = data.get('care_team', [])
    if not care_team:
        care_team = [{
            'name': current_user.username,
            'role': 'provider',
            'contact_protocol': 'Contact through Cloze platform',
            'after_hours': '',
        }]

    plan = SafetyPlan(
        patient_id=patient_id,
        status='draft',
        version=1,
    )
    plan.set_anti_patterns(data.get('anti_patterns', []))
    plan.set_care_team(care_team)
    plan.set_emergency_plan(data.get('emergency_plan', {}))
    plan.provider_notes = data.get('provider_notes', '')

    db.session.add(plan)
    db.session.commit()

    return jsonify(plan.to_dict()), 201


@safety_bp.route("/<int:plan_id>/provider-sections", methods=["PUT"])
@login_required
def update_provider_sections(plan_id):
    """Update provider sections on a plan."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    plan = db.get_or_404(SafetyPlan, plan_id)
    if not current_user.can_access_patient(plan.patient_id):
        abort(403)

    data = request.json or {}

    if 'anti_patterns' in data:
        plan.set_anti_patterns(data['anti_patterns'])
    if 'care_team' in data:
        plan.set_care_team(data['care_team'])
    if 'emergency_plan' in data:
        plan.set_emergency_plan(data['emergency_plan'])
    if 'provider_notes' in data:
        plan.provider_notes = data['provider_notes']

    plan.updated_at = time.time()
    db.session.commit()

    return jsonify(plan.to_dict())


@safety_bp.route("/<int:plan_id>/approve", methods=["POST"])
@login_required
def approve_plan(plan_id):
    """Approve a pending plan -> set status to active, supersede old active."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    plan = db.get_or_404(SafetyPlan, plan_id)
    if not current_user.can_access_patient(plan.patient_id):
        abort(403)

    if plan.status != 'pending_review':
        return jsonify({'error': 'Only pending_review plans can be approved.'}), 400

    # Supersede old active plan
    old_active = SafetyPlan.get_active_plan(plan.patient_id)
    if old_active:
        old_active.status = 'superseded'

    plan.status = 'active'
    plan.approved_at = time.time()
    plan.approved_by = current_user.id
    db.session.commit()

    return jsonify(plan.to_dict())


@safety_bp.route("/<int:plan_id>/reject", methods=["POST"])
@login_required
def reject_plan(plan_id):
    """Reject a pending plan with optional feedback."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    plan = db.get_or_404(SafetyPlan, plan_id)
    if not current_user.can_access_patient(plan.patient_id):
        abort(403)

    if plan.status != 'pending_review':
        return jsonify({'error': 'Only pending_review plans can be rejected.'}), 400

    data = request.json or {}
    feedback = data.get('feedback', '')

    # Move back to draft so patient can revise
    plan.status = 'draft'
    if feedback:
        # Append feedback to provider notes
        existing_notes = plan.provider_notes or ''
        plan.provider_notes = f"{existing_notes}\n\n[Revision requested]: {feedback}".strip()

    plan.updated_at = time.time()
    db.session.commit()

    return jsonify(plan.to_dict())


@safety_bp.route("/pending-reviews", methods=["GET"])
@login_required
def get_pending_reviews():
    """All patients with pending safety plan changes (for provider dashboard)."""
    if not current_user.is_provider() and not current_user.is_admin():
        abort(403)

    # Get patients this provider manages
    if current_user.is_admin():
        pending = SafetyPlan.query.filter_by(status='pending_review').all()
    else:
        patient_ids = [pp.patient_id for pp in
                       ProviderPatient.query.filter_by(provider_id=current_user.id).all()]
        pending = SafetyPlan.query.filter(
            SafetyPlan.patient_id.in_(patient_ids),
            SafetyPlan.status == 'pending_review'
        ).all()

    result = []
    for plan in pending:
        patient = db.session.get(User, plan.patient_id)
        result.append({
            'plan_id': plan.id,
            'patient_id': plan.patient_id,
            'patient_name': patient.username if patient else 'Unknown',
            'version': plan.version,
            'updated_at': plan.updated_at or plan.created_at,
        })

    return jsonify(result)
