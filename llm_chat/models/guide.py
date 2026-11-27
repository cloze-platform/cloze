"""Guides: a page of Markdown a research team writes once and attaches to any
number of chats (FlowChat.guide_id). The participant reads it beside the chat.

Images in a guide come only from the researcher's own media library, as
/media/<public_id> (services/guides.py checks this on save, and the page's
guide sanitiser drops any other image). Stage 4's block editor will replace
how a guide is written, not the Guide itself.
"""
import time

from ..extensions import db


class Guide(db.Model):
    __tablename__ = 'guides'

    TITLE_LIMIT = 120
    BODY_LIMIT = 20_000

    id = db.Column(db.Integer, primary_key=True)
    # The researcher who owns it. Always set from the signed-in user.
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(TITLE_LIMIT), nullable=False)
    body_md = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.Float, default=lambda: time.time())
    updated_at = db.Column(db.Float, default=lambda: time.time(), onupdate=lambda: time.time())
    # Soft delete: chats that used it simply stop showing it.
    deleted_at = db.Column(db.Float, nullable=True)

    def to_dict(self, used_by=None):
        result = {
            'id': self.id,
            'title': self.title,
            'body_md': self.body_md,
            'updated_at': self.updated_at,
        }
        if used_by is not None:
            result['used_by'] = used_by
        return result
