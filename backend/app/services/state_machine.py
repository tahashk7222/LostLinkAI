"""Single source of truth for allowed status transitions."""

from app.core.errors import conflict
from app.models.enums import CaseStatus, MatchStatus, ReportStatus

R, M, C = ReportStatus, MatchStatus, CaseStatus

REPORT_TRANSITIONS: dict[ReportStatus, set[ReportStatus]] = {
    R.DRAFT: {R.ACTIVE, R.CLOSED},
    R.ACTIVE: {R.POTENTIAL_MATCH, R.CONNECTED, R.CLOSED, R.EXPIRED, R.DEACTIVATED},
    R.POTENTIAL_MATCH: {R.ACTIVE, R.CONNECTED, R.CLOSED, R.EXPIRED, R.DEACTIVATED},
    R.CONNECTED: {R.RECOVERED, R.ACTIVE, R.CLOSED, R.DEACTIVATED},
    R.RECOVERED: {R.CLOSED},
    R.CLOSED: set(),
    R.EXPIRED: {R.ACTIVE},
    R.DEACTIVATED: {R.ACTIVE},
}

MATCH_TRANSITIONS: dict[MatchStatus, set[MatchStatus]] = {
    M.POTENTIAL_MATCH: {M.VERIFICATION_PENDING, M.DISMISSED},
    M.VERIFICATION_PENDING: {M.AWAITING_FINDER_REVIEW, M.DISMISSED},
    M.AWAITING_FINDER_REVIEW: {M.VERIFIED, M.REJECTED},
    M.VERIFIED: set(),
    M.REJECTED: set(),
    M.DISMISSED: set(),
}

CASE_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    C.CONNECTED: {C.RECOVERED, C.CLOSED},
    C.RECOVERED: {C.CLOSED},
    C.CLOSED: set(),
}

_TABLES = {ReportStatus: REPORT_TRANSITIONS, MatchStatus: MATCH_TRANSITIONS, CaseStatus: CASE_TRANSITIONS}


def can_transition(current, new) -> bool:
    return current == new or new in _TABLES[type(current)][current]


def transition(obj, new) -> None:
    """Set obj.status = new, or raise 409 if the transition is not allowed."""
    if not can_transition(obj.status, new):
        raise conflict(f"Cannot change status from {obj.status.value} to {new.value}")
    obj.status = new
