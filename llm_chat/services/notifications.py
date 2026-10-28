"""CLOZE-Guard v0 — email notifications via AWS SES.

Sends a deliberately generic, branded HTML alert when a participant message is
flagged. The email carries NO participant identity, NO flagged terms, and NO
conversation reference — only that a safety notification needs attention, with
a link to the secure dashboard where the details live.

Authenticated by the server's IAM role in production (EC2 instance role or ECS
task role). When boto3 or AWS
credentials/sender config are absent (e.g. local dev), this degrades to a
logged no-op rather than raising.
"""

from flask import current_app

SUBJECT = "[Cloze] Safety notification requires attention"


def _dashboard_url():
    return current_app.config["CLOZE_PUBLIC_URL"] + "/provider/dashboard"


def _text_body(url):
    return (
        "Safety notification\n\n"
        "A safety notification in your study requires attention. Please sign in "
        "to your provider dashboard to review the details:\n"
        f"{url}\n\n"
        "This is an automated message from CLOZE-Guard. For privacy, it contains "
        "no participant information — all details are available only within the "
        "secure dashboard."
    )


def _html_body(url):
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f4f4f7;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 12px;">
      <tr><td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e7e5e4;">
          <tr><td style="background:#312E81;padding:20px 28px;">
            <span style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:0.2px;">Cloze</span>
          </td></tr>
          <tr><td style="padding:32px 28px 8px;">
            <h1 style="margin:0 0 12px;font-size:20px;color:#1c1917;">Safety notification</h1>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#44403c;">
              A safety notification in your study requires attention. Please sign in to your provider dashboard to review the details.
            </p>
            <a href="{url}" style="display:inline-block;background:#312E81;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 24px;border-radius:8px;">Open dashboard</a>
          </td></tr>
          <tr><td style="padding:24px 28px 28px;">
            <p style="margin:20px 0 0;border-top:1px solid #f0eeec;padding-top:16px;font-size:12px;line-height:1.5;color:#a8a29e;">
              This is an automated message from CLOZE-Guard. For privacy, it intentionally contains no participant information — all details are available only within the secure dashboard.
            </p>
          </td></tr>
        </table>
        <p style="margin:16px 0 0;font-size:11px;color:#b8b3ae;">Cloze &middot; Clinical conversation platform</p>
      </td></tr>
    </table>
  </body>
</html>"""


def send_guard_email(recipients, patient_id=None):
    """Send a generic safety-notification alert to configured research staff.

    Args:
        recipients: comma-separated recipient address string.
        patient_id: used only for the server-side log line — never in the email.
    """
    sender = current_app.config["CLOZE_GUARD_SENDER"]
    region = current_app.config["AWS_SES_REGION"]

    to_addresses = [e.strip() for e in (recipients or "").split(",") if e.strip()]
    if not sender or not to_addresses:
        current_app.logger.warning(
            "CLOZE-Guard email skipped (sender=%r, recipients=%r)", sender, to_addresses
        )
        return

    try:
        import boto3
    except ImportError:
        current_app.logger.warning("CLOZE-Guard email skipped: boto3 not installed")
        return

    url = _dashboard_url()

    # Local dev uses a named profile (CLOZE_GUARD_AWS_PROFILE=cloze); in prod
    # it is unset and boto3 falls back to the instance or task role.
    profile = current_app.config["CLOZE_GUARD_AWS_PROFILE"]
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()

    try:
        ses = session.client("ses", region_name=region)
        ses.send_email(
            Source=sender,
            Destination={"ToAddresses": to_addresses},
            Message={
                "Subject": {"Data": SUBJECT},
                "Body": {
                    "Text": {"Data": _text_body(url)},
                    "Html": {"Data": _html_body(url)},
                },
            },
        )
        current_app.logger.info(
            "CLOZE-Guard alert emailed to %d recipient(s)%s",
            len(to_addresses),
            f" (patient {patient_id})" if patient_id else "",
        )
    except Exception:
        current_app.logger.exception("CLOZE-Guard SES send failed")
