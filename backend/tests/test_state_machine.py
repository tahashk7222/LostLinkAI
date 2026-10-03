from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.models.enums import CaseStatus, MatchStatus, ReportStatus
from app.services.state_machine import can_transition, transition


def test_valid_match_flow():
    m = SimpleNamespace(status=MatchStatus.POTENTIAL_MATCH)
    for s in (MatchStatus.VERIFICATION_PENDING, MatchStatus.AWAITING_FINDER_REVIEW, MatchStatus.VERIFIED):
        transition(m, s)
    assert m.status == MatchStatus.VERIFIED


def test_cannot_skip_verification():
    m = SimpleNamespace(status=MatchStatus.POTENTIAL_MATCH)
    with pytest.raises(AppError) as e:
        transition(m, MatchStatus.VERIFIED)
    assert e.value.status_code == 409


def test_terminal_states():
    assert not can_transition(ReportStatus.CLOSED, ReportStatus.ACTIVE)
    assert not can_transition(CaseStatus.CLOSED, CaseStatus.CONNECTED)
    assert not can_transition(CaseStatus.RECOVERED, CaseStatus.CONNECTED)
    assert can_transition(ReportStatus.CONNECTED, ReportStatus.RECOVERED)
