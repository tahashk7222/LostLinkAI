"""Lifecycle rules for match suggestions.

A suggestion (MatchCandidate) exists only while both reports are open and the pair still
qualifies. When that stops being true, the uncontested suggestion (POTENTIAL_MATCH) is
withdrawn and the reports return to ACTIVE if nothing else is open for them.

Suggestions already in verification (VERIFICATION_PENDING, AWAITING_FINDER_REVIEW) are never
withdrawn here: a person is working on them and their decision is recorded separately.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ItemReport, MatchCandidate
from app.models.enums import MatchStatus, ReportStatus
from app.services.audit import audit
from app.services.state_machine import transition

OPEN_MATCH = (MatchStatus.POTENTIAL_MATCH, MatchStatus.VERIFICATION_PENDING, MatchStatus.AWAITING_FINDER_REVIEW)


def reopen_if_unmatched(db: Session, report: ItemReport) -> None:
    """Return a report to ACTIVE when it has no open matches left."""
    if report.status != ReportStatus.POTENTIAL_MATCH:
        return
    db.flush()  # autoflush is off: make the caller's pending changes visible to the query
    still_open = db.scalar(select(MatchCandidate.id).where(
        or_(MatchCandidate.lost_report_id == report.id, MatchCandidate.found_report_id == report.id),
        MatchCandidate.status.in_(OPEN_MATCH)).limit(1))
    if still_open is None:
        transition(report, ReportStatus.ACTIVE)


def withdraw_matches(db: Session, report: ItemReport, *, keep: set[tuple[int, int]] = frozenset(),
                     reason: str) -> int:
    """Delete this report's uncontested suggestions, except pairs listed in `keep`.

    `keep` holds (lost_report_id, found_report_id) pairs that still qualify. Returns the count withdrawn.
    """
    rows = db.scalars(select(MatchCandidate).where(
        or_(MatchCandidate.lost_report_id == report.id, MatchCandidate.found_report_id == report.id),
        MatchCandidate.status == MatchStatus.POTENTIAL_MATCH)).all()
    withdrawn, counterparts = 0, []
    for m in rows:
        if (m.lost_report_id, m.found_report_id) in keep:
            continue
        counterparts += [m.lost_report, m.found_report]
        audit(db, "match.withdrawn", None, "match", m.id, reason=reason)
        db.delete(m)
        withdrawn += 1
    db.flush()
    for other in counterparts:
        reopen_if_unmatched(db, other)
    reopen_if_unmatched(db, report)
    return withdrawn
