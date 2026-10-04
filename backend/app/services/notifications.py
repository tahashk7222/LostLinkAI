"""Notification Agent/Service.

Messages are templated and deliberately contain no contact details, private
details or exact locations. In-app delivery is implemented; an email channel can
be added behind `send_email` without changing callers.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Notification

logger = logging.getLogger("lostlink.notify")

TEMPLATES: dict[str, tuple[str, str]] = {
    "match_owner": (
        "Potential match for your lost item",
        "LostLink AI found a potential match for your lost item \"{item}\". "
        "Open it to review the details and verify ownership.",
    ),
    "match_finder": (
        "Your found item may match a lost report",
        "Someone's lost-item report may match the \"{item}\" you found. "
        "If they ask to verify ownership, you'll be asked to decide whether they are the owner.",
    ),
    "verification_submitted": (
        "Ownership verification ready for your decision",
        "A possible owner submitted verification for the \"{item}\" you found. "
        "Their answers are private and are not shown to you. Open the match to accept or reject.",
    ),
    "verification_accepted": (
        "Verification passed",
        "Ownership verification completed successfully for \"{item}\". The finder will confirm whether they still "
        "have the item. Messages open once they do.",
    ),
    "verification_rejected": (
        "Ownership not confirmed",
        "The finder could not confirm ownership of \"{item}\" from your answers. "
        "Your lost report stays active and LostLink AI will keep looking.",
    ),
    "possession_confirmed": (
        "The finder still has the item",
        "The finder confirmed they still have \"{item}\". Use in-app messages to arrange the handover, "
        "then mark it recovered.",
    ),
    "case_connected": (
        "Verification passed — please confirm",
        "Ownership verification completed successfully for \"{item}\". Please confirm whether you still have the item.",
    ),
    "new_message": ("New message", "You have a new message about \"{item}\"."),
    "case_recovered": ("Item marked recovered", "\"{item}\" has been marked as recovered. Thank you for using LostLink AI!"),
    "case_closed": ("Case closed", "The case for \"{item}\" has been closed."),
    "report_deactivated": ("Report deactivated", "Your report \"{item}\" was deactivated by a moderator."),
}


def notify(db: Session, user_id: int, kind: str, link: str | None = None, **fields) -> Notification:
    title, body = TEMPLATES[kind]
    n = Notification(user_id=user_id, type=kind, title=title, message=body.format(**fields), link=link)
    db.add(n)
    send_email(user_id, title)
    return n


def send_email(user_id: int, subject: str) -> None:
    """Email channel placeholder: logs only. Configure SMTP/provider here later."""
    logger.info("email channel not configured; notification for user %s: %s", user_id, subject)
