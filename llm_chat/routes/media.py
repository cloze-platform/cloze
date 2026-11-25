"""Researcher media library and media serving.

Researchers upload and manage their own images under /api/provider/media.
Everyone fetches media from /media/<public_id>, which checks access first
(llm_chat/media/access.py) and then hands over the file.
"""
import os
import time

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required

from ..extensions import db
from ..media import access
from ..media.images import CONTENT_TYPE, EXTENSION, MAX_UPLOAD_BYTES, ImageRejected, process_image
from ..media.store import get_store
from ..models import MediaAsset, MediaRendition
from ..utils.decorators import role_required
from .provider import _log_provider_action

media_bp = Blueprint("media", __name__)

LABEL_MAX = 100
ALT_TEXT_MAX = 300

# Renditions a browser may fetch, and which one a bare /media/<id> means.
# A video's 'original' upload is never served.
SERVED_ROLES = {'display', 'thumb', 'mp4', 'poster'}
DEFAULT_ROLE = {MediaAsset.KIND_IMAGE: 'display', MediaAsset.KIND_VIDEO: 'mp4'}
# Presigned URL lifetime. Video gets longer so seeking late in a long video still works.
URL_LIFETIME = {MediaAsset.KIND_IMAGE: 600, MediaAsset.KIND_VIDEO: 7200}

UPLOADS_OFF = 'Media uploads are not set up on this instance.'


@media_bp.route("/media/<public_id>")
@login_required
def serve_media(public_id):
    asset = access.viewable_asset(current_user, public_id)
    if asset is None:
        abort(404)
    role = request.args.get('r') or DEFAULT_ROLE.get(asset.kind)
    rendition = asset.rendition(role) if role in SERVED_ROLES else None
    store = get_store()
    if rendition is None or store is None:
        abort(404)
    return store.serve(rendition, URL_LIFETIME.get(asset.kind, 600))


# ── Library (researchers) ─────────────────────────────────────

@media_bp.route("/api/provider/media", methods=['GET'])
@role_required('provider')
def list_media():
    return jsonify({
        'assets': [a.to_dict() for a in access.library(current_user)],
        'uploads_enabled': get_store() is not None,
        'max_upload_bytes': MAX_UPLOAD_BYTES,
    })


def _clean_text(value, limit, name):
    value = (value or '').strip()
    if len(value) > limit:
        raise ValueError(f'{name} must be {limit} characters or fewer.')
    return value


@media_bp.route("/api/provider/media", methods=['POST'])
@role_required('provider')
def upload_media():
    store = get_store()
    if store is None:
        return jsonify({'error': UPLOADS_OFF}), 503

    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify({'error': 'Choose an image to upload.'}), 400
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({'error': 'That image is over 10 MB.'}), 413

    filename = os.path.basename(upload.filename)[:255]
    try:
        label = _clean_text(request.form.get('label'), LABEL_MAX, 'Label') \
            or os.path.splitext(filename)[0][:LABEL_MAX] or 'Image'
        alt_text = _clean_text(request.form.get('alt_text'), ALT_TEXT_MAX, 'Alt text') or None
        image = process_image(data)
    except (ValueError, ImageRejected) as e:
        return jsonify({'error': str(e)}), 400

    asset = MediaAsset(owner_id=current_user.id, created_by=current_user.id,
                       kind=MediaAsset.KIND_IMAGE, status=MediaAsset.STATUS_READY,
                       label=label, alt_text=alt_text, original_filename=filename,
                       width=image.width, height=image.height)
    db.session.add(asset)
    db.session.flush()  # assigns public_id

    try:
        for role, rendition in image.renditions.items():
            key = f'media/{current_user.id}/{asset.public_id}/{role}.{EXTENSION}'
            store.put(key, rendition.data, CONTENT_TYPE)
            asset.renditions.append(MediaRendition(
                role=role, storage_key=key, content_type=CONTENT_TYPE,
                byte_size=len(rendition.data), width=rendition.width, height=rendition.height))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Storing an uploaded image failed')
        return jsonify({'error': 'The image could not be stored. Please try again.'}), 502

    _log_provider_action('upload_media', 'media_asset', asset.id,
                         {'public_id': asset.public_id, 'label': label, 'bytes': len(data)})
    db.session.commit()
    return jsonify(asset.to_dict()), 201


@media_bp.route("/api/provider/media/<public_id>", methods=['PATCH'])
@role_required('provider')
def update_media(public_id):
    asset = access.owned_asset(current_user, public_id)
    if asset is None:
        abort(404)
    data = request.json or {}
    try:
        if 'label' in data:
            label = _clean_text(data['label'], LABEL_MAX, 'Label')
            if not label:
                raise ValueError('Label cannot be empty.')
            asset.label = label
        if 'alt_text' in data:
            asset.alt_text = _clean_text(data['alt_text'], ALT_TEXT_MAX, 'Alt text') or None
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.session.commit()
    return jsonify(asset.to_dict())


@media_bp.route("/api/provider/media/<public_id>", methods=['DELETE'])
@role_required('provider')
def delete_media(public_id):
    """Remove an asset from the library. Places already using it keep showing it."""
    asset = access.owned_asset(current_user, public_id)
    if asset is None:
        abort(404)
    asset.deleted_at = time.time()
    _log_provider_action('delete_media', 'media_asset', asset.id, {'public_id': asset.public_id})
    db.session.commit()
    return jsonify({'status': 'success'})
