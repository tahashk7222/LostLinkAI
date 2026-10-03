from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.ai.verification import MAX_ANSWER_LEN, build_questions, evaluate_answers
from app.api.deps import DB, CurrentUser
from app.core.errors import bad_request, conflict
from app.models import Case, ItemReport, MatchCandidate, Verification
from app.models.enums import MatchStatus, ReportStatus
from app.schemas.workflow import VerificationAnswersIn, VerifyDecisionIn
from app.services.audit import audit
from app.services.matches import get_match_for, match_summary
from app.services.notifications import notify
from app.services.state_machine import transition

router = APIRouter(prefix="/matches", tags=["matches & verification"])

OPEN_MATCH = (MatchStatus.POTENTIAL_MATCH, MatchStatus.VERIFICATION_PENDING, MatchStatus.AWAITING_FINDER_REVIEW)


def _latest_verification(db, match_id: int) -> Verification | None:
    return db.scalar(select(Verification).where(Verification.match_id == match_id).order_by(Verification.id.desc()))


def _reopen_if_unmatched(db, report: ItemReport) -> None:
    """Return a report to ACTIVE when it has no open matches left."""
    if report.status != ReportStatus.POTENTIAL_MATCH:
        return
    db.flush()  # autoflush is off: make the caller's status change visible to the query
    still_open = db.scalar(select(MatchCandidate.id).where(
        or_(MatchCandidate.lost_report_id == report.id, MatchCandidate.found_report_id == report.id),
        MatchCandidate.status.in_(OPEN_MATCH)).limit(1))
    if still_open is None:
        transition(report, ReportStatus.ACTIVE)


@router.get("")
def my_matches(user: CurrentUser, db: DB):
    mine = select(ItemReport.id).where(ItemReport.user_id == user.id)
    rows = db.scalars(select(MatchCandidate).where(
        or_(MatchCandidate.lost_report_id.in_(mine), MatchCandidate.found_report_id.in_(mine)),
        MatchCandidate.status != MatchStatus.DISMISSED,
    ).order_by(MatchCandidate.created_at.desc())).all()
    return {"matches": [match_summary(db, m, user) for m in rows]}


@router.get("/{match_id}")
def get_match(match_id: int, user: CurrentUser, db: DB):
    m, _ = get_match_for(db, user, match_id)
    return match_summary(db, m, user)


@router.post("/{match_id}/dismiss")
def dismiss(match_id: int, user: CurrentUser, db: DB):
    """Owner says: this is not my item."""
    m, _ = get_match_for(db, user, match_id, roles=("owner",))
    transition(m, MatchStatus.DISMISSED)
    _reopen_if_unmatched(db, m.lost_report)
    _reopen_if_unmatched(db, m.found_report)
    audit(db, "match.dismissed", user.id, "match", m.id)
    db.commit()
    return match_summary(db, m, user)


@router.post("/{match_id}/verification", status_code=201)
def start_verification(match_id: int, user: CurrentUser, db: DB):
    """Owner requests to verify ownership; the Verification Agent picks private questions."""
    m, _ = get_match_for(db, user, match_id, roles=("owner",))
    if m.found_report.status not in (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH):
        raise conflict("This found item is no longer available for verification")
    transition(m, MatchStatus.VERIFICATION_PENDING)
    v = Verification(match_id=m.id, questions=build_questions(m.found_report))
    db.add(v)
    audit(db, "verification.started", user.id, "match", m.id)
    db.commit()
    return {"status": v.result, "questions": v.questions}


@router.get("/{match_id}/verification")
def get_verification(match_id: int, user: CurrentUser, db: DB):
    m, role = get_match_for(db, user, match_id)
    v = _latest_verification(db, m.id)
    if v is None:
        return {"status": None, "match_status": m.status}
    out = {"status": v.result, "match_status": m.status, "questions": v.questions,
           "submitted_at": v.submitted_at, "decided_at": v.decided_at}
    if role == "owner":
        out["my_answers"] = v.answers
    elif role == "finder" and v.answers is not None:
        out.update(answers=v.answers, advisory_score=v.advisory_score, advisory_notes=v.advisory_notes)
    return out


@router.post("/{match_id}/verification/answers")
def submit_answers(match_id: int, body: VerificationAnswersIn, user: CurrentUser, db: DB):
    m, _ = get_match_for(db, user, match_id, roles=("owner",))
    v = _latest_verification(db, m.id)
    if v is None or m.status != MatchStatus.VERIFICATION_PENDING:
        raise conflict("Start verification before submitting answers")
    valid_ids = {q["id"] for q in v.questions}
    answers = {k: v_.strip() for k, v_ in body.answers.items() if k in valid_ids and v_ and v_.strip()}
    if any(len(a) > MAX_ANSWER_LEN for a in answers.values()):
        raise bad_request(f"Answers must be under {MAX_ANSWER_LEN} characters")
    required = [q["id"] for q in v.questions if not q.get("optional")]
    if not any(answers.get(q) for q in required):
        raise bad_request("Please answer at least one of the required questions")

    score, notes = evaluate_answers(m.found_report, v.questions, answers)
    v.answers, v.advisory_score, v.advisory_notes = answers, score, notes
    v.result, v.submitted_at = "SUBMITTED", datetime.now(timezone.utc)
    transition(m, MatchStatus.AWAITING_FINDER_REVIEW)
    notify(db, m.found_report.user_id, "verification_submitted", link=f"/matches/{m.id}/verify",
           item=m.found_report.name)
    audit(db, "verification.submitted", user.id, "match", m.id)
    db.commit()
    return {"status": v.result, "match_status": m.status}


@router.post("/{match_id}/verify")
def decide(match_id: int, body: VerifyDecisionIn, user: CurrentUser, db: DB):
    """The finder — a human holding the item — accepts or rejects the owner's answers."""
    m, _ = get_match_for(db, user, match_id, roles=("finder",))
    v = _latest_verification(db, m.id)
    if v is None or m.status != MatchStatus.AWAITING_FINDER_REVIEW:
        raise conflict("There are no answers waiting for review")
    v.decided_by, v.decided_at = user.id, datetime.now(timezone.utc)
    lost, found = m.lost_report, m.found_report

    if body.decision == "ACCEPT":
        if found.status not in (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH):
            raise conflict("This found item is already connected to another owner")
        v.result = "ACCEPTED"
        transition(m, MatchStatus.VERIFIED)
        transition(lost, ReportStatus.CONNECTED)
        transition(found, ReportStatus.CONNECTED)
        case = Case(match_id=m.id)
        db.add(case)
        db.flush()
        notify(db, lost.user_id, "verification_accepted", link=f"/cases/{case.id}", item=lost.name)
        notify(db, found.user_id, "case_connected", link=f"/cases/{case.id}", item=found.name)
        audit(db, "verification.accepted", user.id, "match", m.id, case_id=case.id, advisory=v.advisory_score)
    else:
        v.result = "REJECTED"
        transition(m, MatchStatus.REJECTED)
        _reopen_if_unmatched(db, lost)
        _reopen_if_unmatched(db, found)
        notify(db, lost.user_id, "verification_rejected", link=f"/matches/{m.id}", item=lost.name)
        audit(db, "verification.rejected", user.id, "match", m.id, advisory=v.advisory_score)
    db.commit()
    return match_summary(db, m, user)
