"""Who may see and use which media. Every media route goes through here.

- A researcher sees and uses only the assets they own.
- A participant sees only assets owned by their own researcher.
- Admins see everything.

Anything else is reported as "not found", so one researcher can't even confirm
that another researcher's asset exists. Researchers never hold storage
credentials, so this check is the boundary between researchers' content.

"Owner" is a single researcher login. If research teams that share content are
added later, ownership moves to the team here and nowhere else.
"""
import uuid

from ..models import MediaAsset
from ..utils.settings_resolution import get_provider_id_for_patient


def canonical_id(public_id):
    """The canonical form of a public id, or None if it isn't one."""
    try:
        return str(uuid.UUID(str(public_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def library(user):
    """The assets a researcher can manage and attach: their own, not deleted."""
    return (MediaAsset.query
            .filter_by(owner_id=user.id, deleted_at=None)
            .order_by(MediaAsset.created_at.desc()))


def owned_asset(user, public_id):
    """An asset this researcher owns and can still attach, or None."""
    pid = canonical_id(public_id)
    if pid is None or not user.is_provider():
        return None
    return MediaAsset.query.filter_by(public_id=pid, owner_id=user.id, deleted_at=None).first()


def can_view(user, asset):
    if asset is None or asset.status != MediaAsset.STATUS_READY:
        return False
    if user.is_admin():
        return True
    if user.is_provider():
        return asset.owner_id == user.id
    if user.is_patient():
        return get_provider_id_for_patient(user.id) == asset.owner_id
    return False


def viewable_asset(user, public_id):
    """An asset this user may see, or None. Soft-deleted assets stay viewable
    so that what participants were already shown keeps working."""
    pid = canonical_id(public_id)
    if pid is None:
        return None
    asset = MediaAsset.query.filter_by(public_id=pid).first()
    return asset if can_view(user, asset) else None
