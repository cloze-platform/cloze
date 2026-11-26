"""Speakers: the characters a chat's replies can be split between.

A researcher keeps a set of speakers (for example Sky and Star), each with a
name, a role and a picture from their media library. A study-design chat picks
its cast from them (FlowChat.speaker_ids) and a main speaker. In a chat with a
cast, a reply's lines that start with a cast member's name ("Sky: ...") show
under that speaker; see services/speakers.py.

Speakers only change how a reply is shown. The model's reply is stored and
sent back to the model exactly as written, so the research team's prompt
works the same in Cloze as anywhere else.
"""
import time

from ..extensions import db


class Speaker(db.Model):
    __tablename__ = 'speakers'

    NAME_LIMIT = 40
    ROLE_LIMIT = 60

    id = db.Column(db.Integer, primary_key=True)
    # The researcher who owns it. Always set from the signed-in user.
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(NAME_LIMIT), nullable=False)
    role = db.Column(db.String(ROLE_LIMIT), nullable=True)
    picture_asset_id = db.Column(db.Integer, db.ForeignKey('media_assets.id', ondelete='SET NULL'),
                                 nullable=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.Float, default=lambda: time.time())
    # Soft delete: chats that named the speaker in their cast simply skip it,
    # and nothing that points at it can block the delete.
    deleted_at = db.Column(db.Float, nullable=True)

    picture = db.relationship('MediaAsset', foreign_keys=[picture_asset_id])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'picture': self.picture.to_dict() if self.picture else None,
            'order_index': self.order_index,
        }
