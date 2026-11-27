"""A researcher's guides: Markdown pages attached to chats (see
services/guides.py). Each researcher sees and changes only their own; anyone
else's is "not found"."""
import time

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user

from ..extensions import db
from ..models import FlowChat, FlowPhase, Guide, StudyFlow
from ..services.guides import apply_guide_fields
from ..utils.decorators import role_required
from .provider import _log_provider_action

guides_bp = Blueprint("guides", __name__)


def _own_guides():
    return (Guide.query.filter(Guide.owner_id == current_user.id, Guide.deleted_at.is_(None))
            .order_by(Guide.title, Guide.id))


def _own_guide_or_404(guide_id):
    guide = db.session.get(Guide, guide_id)
    if guide is None or guide.owner_id != current_user.id or guide.deleted_at is not None:
        abort(404)
    return guide


def _used_by():
    """{guide id: [{chat_id, title, flow}]} for the researcher's chats."""
    rows = (db.session.query(FlowChat.guide_id, FlowChat.id, FlowChat.title, StudyFlow.name)
            .join(FlowPhase, FlowChat.phase_id == FlowPhase.id)
            .join(StudyFlow, FlowPhase.flow_id == StudyFlow.id)
            .filter(StudyFlow.provider_id == current_user.id, FlowChat.guide_id.isnot(None))
            .order_by(StudyFlow.name, FlowChat.title).all())
    used = {}
    for guide_id, chat_id, title, flow in rows:
        used.setdefault(guide_id, []).append({"chat_id": chat_id, "title": title, "flow": flow})
    return used


@guides_bp.route("/api/provider/guides", methods=["GET"])
@role_required("provider")
def list_guides():
    used = _used_by()
    return jsonify({"guides": [g.to_dict(used.get(g.id, [])) for g in _own_guides()]})


@guides_bp.route("/api/provider/guides", methods=["POST"])
@role_required("provider")
def create_guide():
    guide = Guide(owner_id=current_user.id, body_md="")
    try:
        apply_guide_fields(guide, request.json or {}, current_user)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db.session.add(guide)
    db.session.flush()
    _log_provider_action("guide_created", "guide", guide.id, {"title": guide.title})
    db.session.commit()
    return jsonify(guide.to_dict([])), 201


@guides_bp.route("/api/provider/guides/<int:guide_id>", methods=["PUT"])
@role_required("provider")
def update_guide(guide_id):
    guide = _own_guide_or_404(guide_id)
    try:
        apply_guide_fields(guide, request.json or {}, current_user)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    _log_provider_action("guide_updated", "guide", guide.id, {"title": guide.title})
    db.session.commit()
    return jsonify(guide.to_dict(_used_by().get(guide.id, [])))


@guides_bp.route("/api/provider/guides/<int:guide_id>", methods=["DELETE"])
@role_required("provider")
def delete_guide(guide_id):
    """Remove a guide. Chats that used it stop showing it; the text is kept."""
    guide = _own_guide_or_404(guide_id)
    guide.deleted_at = time.time()
    _log_provider_action("guide_deleted", "guide", guide.id, {"title": guide.title})
    db.session.commit()
    return jsonify({"status": "success"})
