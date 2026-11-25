"""Researcher-uploaded media: images now, video later.

A MediaAsset is what a researcher uploads and refers to (by its random
public_id, as /media/<public_id>). Its files are MediaRenditions: an image has a
'display' and a 'thumb' rendition; a video will have a private 'original', an
'mp4' and a 'poster'. Adding a kind of rendition needs no schema change.

Who may see an asset is decided in one place, llm_chat/media/access.py.
"""
import time
import uuid

from ..extensions import db


class MediaAsset(db.Model):
    __tablename__ = 'media_assets'

    KIND_IMAGE = 'image'
    KIND_VIDEO = 'video'

    STATUS_PENDING = 'pending'   # video: uploaded straight to storage, not yet confirmed
    STATUS_READY = 'ready'
    STATUS_FAILED = 'failed'

    id = db.Column(db.Integer, primary_key=True)
    # The only id that leaves the server. Random, so asset URLs can't be guessed.
    public_id = db.Column(db.String(36), unique=True, nullable=False, index=True,
                          default=lambda: str(uuid.uuid4()))
    # The researcher who owns it. Always set from the signed-in user, never the request.
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    label = db.Column(db.String(100), nullable=False)
    alt_text = db.Column(db.String(300), nullable=True)
    # Shown in the library only; never used to build a storage key.
    original_filename = db.Column(db.String(255), nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    duration_seconds = db.Column(db.Float, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.Float, default=lambda: time.time())
    # Soft delete: gone from the library, still served where it is already used,
    # so there is a record of what participants were shown.
    deleted_at = db.Column(db.Float, nullable=True)

    renditions = db.relationship('MediaRendition', backref='asset', cascade='all, delete-orphan',
                                 lazy='selectin')

    def rendition(self, role):
        return next((r for r in self.renditions if r.role == role), None)

    @property
    def url(self):
        return f'/media/{self.public_id}'

    def to_dict(self):
        thumb = self.rendition('thumb')
        return {
            'id': self.public_id,
            'kind': self.kind,
            'status': self.status,
            'label': self.label,
            'alt_text': self.alt_text,
            'original_filename': self.original_filename,
            'width': self.width,
            'height': self.height,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at,
            'url': self.url,
            'thumb_url': f'{self.url}?r=thumb' if thumb else self.url,
        }


class MediaRendition(db.Model):
    """One stored file of an asset."""
    __tablename__ = 'media_renditions'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('media_assets.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    # media/<owner_id>/<public_id>/<role>.<ext>, built by the server.
    storage_key = db.Column(db.String(255), unique=True, nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)

    __table_args__ = (db.UniqueConstraint('asset_id', 'role'),)
