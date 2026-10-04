"""Admin moderation decisions on reports: approve (recorded review) and reject (with a reason).

Post-moderation: reports go live when created. Approve confirms a report after review and changes no status.
Reject moves an open report to DEACTIVATED, which is already excluded from matching, and stores why. Reports in a
recovery case are not rejected here: the case must be closed first.
"""

from app.core.errors import conflict
from app.models import ItemReport
from app.models.entities import utcnow
from app.models.enums import ModerationReason, ReportStatus
from app.services.audit import audit
from app.services.match_lifecycle import withdraw_matches
from app.services.notifications import notify
from app.services.state_machine import transition

REVIEWABLE = (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH)


def approve_report(db, admin, report: ItemReport) -> None:
    if report.status not in REVIEWABLE:
        raise conflict("Only an open report can be approved")
    report.moderated_by, report.moderated_at = admin.id, utcnow()
    report.moderation_reason, report.moderation_note = None, None
    audit(db, "admin.report_approved", admin.id, "report", report.id, status=report.status.value)


def reject_report(db, admin, report: ItemReport, reason: ModerationReason, note: str | None) -> None:
    if report.status not in REVIEWABLE:
        raise conflict("Only an open report can be rejected. Close its case first if it is in recovery.")
    previous = report.status.value
    transition(report, ReportStatus.DEACTIVATED)
    report.moderation_reason, report.moderation_note = reason.value, (note or None)
    report.moderated_by, report.moderated_at = admin.id, utcnow()
    withdraw_matches(db, report, reason="report rejected by admin")
    notify(db, report.user_id, "report_deactivated", link=f"/reports/{report.id}", item=report.name)
    # The reason is on the report for admins. The audit entry keeps only the code, never the free-text note.
    audit(db, "admin.report_rejected", admin.id, "report", report.id, reason=reason.value, previous=previous)
