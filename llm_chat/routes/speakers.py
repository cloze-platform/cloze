"""A researcher's speakers: the characters their chats' replies can be split
between (see services/speakers.py). Each researcher sees and changes only
their own; anyone else's is "not found"."""
import time

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user

from ..extensions import db
from ..models import Speaker
from ..services.speakers import apply_speaker_fields
from ..utils.decorators import role_required
from .provider import _log_provider_action

speakers_bp = Blueprint("speakers", __name__)


def _own_speakers():
    return (Speaker.query.filter(Speaker.owner_id == current_user.id, Speaker.deleted_at.is_(None))
            .order_by(Speaker.order_index, Speaker.id))


def _own_speaker_or_404(speaker_id):
    speaker = db.session.get(Speaker, speaker_id)
    if speaker is None or speaker.owner_id != current_user.id or speaker.deleted_at is not None:
        abort(404)
    return speaker


@speakers_bp.route("/api/provider/speakers", methods=["GET"])
@role_required("provider")
def list_speakers():
    return jsonify({"speakers": [s.to_dict() for s in _own_speakers()]})


@speakers_bp.route("/api/provider/speakers", methods=["POST"])
@role_required("provider")
def create_speaker():
    data = request.json or {}
    # No ORDER BY with an aggregate: Postgres refuses it (SQLite doesn't care).
    last = (db.session.query(db.func.max(Speaker.order_index))
            .filter(Speaker.owner_id == current_user.id, Speaker.deleted_at.is_(None)).scalar())
    speaker = Speaker(owner_id=current_user.id, order_index=(last if last is not None else -1) + 1)
    try:
        apply_speaker_fields(speaker, data, current_user)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db.session.add(speaker)
    db.session.flush()
    _log_provider_action("speaker_created", "speaker", speaker.id, {"name": speaker.name})
    db.session.commit()
    return jsonify(speaker.to_dict()), 201


@speakers_bp.route("/api/provider/speakers/<int:speaker_id>", methods=["PUT"])
@role_required("provider")
def update_speaker(speaker_id):
    speaker = _own_speaker_or_404(speaker_id)
    try:
        apply_speaker_fields(speaker, request.json or {}, current_user)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    _log_provider_action("speaker_updated", "speaker", speaker.id, {"name": speaker.name})
    db.session.commit()
    return jsonify(speaker.to_dict())


@speakers_bp.route("/api/provider/speakers/<int:speaker_id>", methods=["DELETE"])
@role_required("provider")
def delete_speaker(speaker_id):
    """Remove a speaker. Chats that had it in their cast skip it from now on;
    replies already shown keep their text, which still has the name."""
    speaker = _own_speaker_or_404(speaker_id)
    speaker.deleted_at = time.time()
    _log_provider_action("speaker_deleted", "speaker", speaker.id, {"name": speaker.name})
    db.session.commit()
    return jsonify({"status": "success"})


@speakers_bp.route("/api/provider/speaker-order", methods=["PUT"])
@role_required("provider")
def reorder_speakers():
    """{"speaker_ids": [...]}: every one of the researcher's speakers, once."""
    ids = (request.json or {}).get("speaker_ids")
    speakers = _own_speakers().all()
    if (not isinstance(ids, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in ids)
            or sorted(ids) != sorted(s.id for s in speakers)):
        return jsonify({"error": "speaker_ids must list each of your speakers once."}), 400
    by_id = {s.id: s for s in speakers}
    for index, speaker_id in enumerate(ids):
        by_id[speaker_id].order_index = index
    db.session.commit()
    return jsonify({"speakers": [s.to_dict() for s in _own_speakers()]})
