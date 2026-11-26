"""CLOZE-Guard v0 — keyword pre-classifier.

A first-pass safety screen ahead of a real classifier. When a participant
message contains any provider-configured keyword, this creates an
EscalationEvent (surfaced on the provider dashboard) and triggers an email
notification to configured research staff.

Designed so a real classifier can later replace `_find_hits` without touching
the alert/email/dashboard pipeline. Callers must wrap invocation in try/except
so a scan failure can never block a participant's chat.
"""

import json
import re
import time

from flask import current_app

from ..extensions import db
from ..models import ProviderFeatureFlags, EscalationEvent
from ..utils.settings_resolution import get_provider_id_for_patient


def _find_hits(text, keywords):
    """Case-insensitive, word-boundary match of keywords against text."""
    hits = []
    for kw in keywords:
        kw = (kw or "").strip()
        if kw and re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
            hits.append(kw)
    return hits


def _already_escalated(patient_id, conversation_id, client_message_id, text):
    """The event already raised for this message, if a send of it was retried
    (same client_message_id and text). Retries come within minutes, so only
    the last day's events are checked."""
    recent = EscalationEvent.query.filter(
        EscalationEvent.patient_id == patient_id,
        EscalationEvent.event_type == "keyword_match",
        EscalationEvent.created_at > time.time() - 86400,
    ).all()
    for event in recent:
        try:
            context = json.loads(event.context or "{}")
        except (TypeError, ValueError):
            continue
        if (context.get("client_message_id") == client_message_id
                and context.get("conversation_id") == conversation_id
                and context.get("snippet") == text[:280]):
            return event
    return None


def scan_and_escalate(patient, conversation, text, client_message_id=None):
    """Scan a participant message; escalate + notify on a keyword hit.

    Returns the created EscalationEvent, or None if nothing matched / Guard
    is disabled for this patient's provider. A message the page sent before
    (same client_message_id, retried after its reply failed) is only
    escalated once: the earlier event is returned and nobody is emailed again.
    """
    provider_id = get_provider_id_for_patient(patient.id)
    if not provider_id:
        return None

    flags = ProviderFeatureFlags.query.filter_by(provider_id=provider_id).first()
    if not flags or not flags.guard_enabled or not flags.guard_keywords:
        return None

    try:
        keywords = json.loads(flags.guard_keywords)
    except (TypeError, ValueError):
        return None
    if not isinstance(keywords, list):
        return None

    hits = _find_hits(text, keywords)
    if not hits:
        return None

    if client_message_id:
        earlier = _already_escalated(patient.id, conversation.id, client_message_id, text)
        if earlier is not None:
            return earlier

    event = EscalationEvent(
        event_type="keyword_match",
        severity="critical",
        patient_id=patient.id,
        provider_id=provider_id,
        description=f"Flagged term(s): {', '.join(hits)}",
        context=json.dumps({
            "keywords": hits,
            "conversation_id": conversation.id,
            "client_message_id": client_message_id,
            "snippet": text[:280],
        }),
    )
    db.session.add(event)
    db.session.commit()

    # Email is best-effort and must never raise into the request path.
    # The notification is intentionally generic — no patient/keyword/conversation
    # data leaves the app; staff review details in the dashboard.
    if flags.guard_notify_email:
        try:
            from .notifications import send_guard_email
            send_guard_email(flags.guard_notify_email, patient_id=patient.id)
        except Exception:
            current_app.logger.exception("CLOZE-Guard: email notification failed")

    return event
