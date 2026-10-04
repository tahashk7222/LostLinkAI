"""Case status changes and what they do to the two reports (single place for the recovery lifecycle).

Used by the owner and finder route (`PUT /cases/{id}/status`) and the admin close action, so the rules live once.
Archiving: an item that is recovered or whose case is closed gets `archived_at`. The record is kept, never deleted.
"""

from app.models import Case, ItemReport
from app.models.enums import CaseStatus, ReportStatus
from app.models.entities import utcnow
from app.services.audit import audit
from app.services.notifications import notify
from app.services.state_machine import transition


def set_case_status(db, case: Case, new: CaseStatus, actor_id: int, notify_ids: tuple[int, ...],
                    audit_action: str = "case.status") -> None:
    """Change the case status and the status of both reports. Caller commits."""
    transition(case, new)
    m = case.match
    lost, found = m.lost_report, m.found_report
    if new == CaseStatus.RECOVERED:
        for r in (lost, found):
            transition(r, ReportStatus.RECOVERED)
        for uid in notify_ids:
            notify(db, uid, "case_recovered", link=f"/cases/{case.id}", item=lost.name)
    elif new == CaseStatus.CLOSED:
        for r in (lost, found):
            if r.status == ReportStatus.CONNECTED:  # closed without recovery: reports reopen
                transition(r, ReportStatus.ACTIVE)
            elif r.status == ReportStatus.RECOVERED:
                transition(r, ReportStatus.CLOSED)
        for uid in notify_ids:
            notify(db, uid, "case_closed", link=f"/cases/{case.id}", item=lost.name)
    for r in (lost, found):
        archive_if_out_of_circulation(db, r, actor_id)
    audit(db, audit_action, actor_id, "case", case.id, status=new.value)


def archive_if_out_of_circulation(db, report: ItemReport, actor_id: int) -> None:
    """Stamp archived_at once a report is RECOVERED or CLOSED. Idempotent."""
    if report.status in (ReportStatus.RECOVERED, ReportStatus.CLOSED) and report.archived_at is None:
        report.archived_at = utcnow()
        audit(db, "item.archived", actor_id, "report", report.id, status=report.status.value)
