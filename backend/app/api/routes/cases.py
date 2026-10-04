"""Recovery workflow: controlled communication between verified owner and finder.

Contact details are never exchanged by the system; parties talk through in-app
messages and are identified by first name only.
"""

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.api.deps import DB, CurrentUser
from app.core.errors import conflict, not_found
from app.models import Case, ItemReport, MatchCandidate, Message, User
from app.models.enums import CaseStatus, ReportStatus, Role
from app.schemas.workflow import CaseStatusIn, MessageIn
from app.services.audit import audit
from app.services.case_lifecycle import set_case_status
from app.services.notifications import notify
from app.services.reports import load_report, to_public
from app.services.state_machine import transition

router = APIRouter(prefix="/cases", tags=["cases & messages"])


def _get_case(db, user: User, case_id: int, allow_admin: bool = True) -> tuple[Case, str]:
    case = db.get(Case, case_id)
    if case is None:
        raise not_found("Case")
    m = case.match
    if m.lost_report.user_id == user.id:
        return case, "owner"
    if m.found_report.user_id == user.id:
        return case, "finder"
    if allow_admin and user.role == Role.ADMIN:
        return case, "admin"
    raise not_found("Case")


def _case_out(db, case: Case, role: str, user: User) -> dict:
    m = case.match
    first = lambda u: u.name.split(" ")[0]  # noqa: E731
    return {
        "id": case.id,
        "status": case.status,
        "match_id": m.id,
        "my_role": role,
        "owner_name": first(m.lost_report.owner),
        "finder_name": first(m.found_report.owner),
        "lost_report": to_public(load_report(db, m.lost_report_id), user),
        "found_report": to_public(load_report(db, m.found_report_id), user),
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


@router.get("")
def list_cases(user: CurrentUser, db: DB):
    mine = select(ItemReport.id).where(ItemReport.user_id == user.id)
    rows = db.scalars(select(Case).join(MatchCandidate).where(
        or_(MatchCandidate.lost_report_id.in_(mine), MatchCandidate.found_report_id.in_(mine))
    ).order_by(Case.updated_at.desc())).all()
    return {"cases": [_case_out(db, c, _get_case(db, user, c.id)[1], user) for c in rows]}


@router.get("/{case_id}")
def get_case(case_id: int, user: CurrentUser, db: DB):
    case, role = _get_case(db, user, case_id)
    return _case_out(db, case, role, user)


@router.put("/{case_id}/status")
def update_case_status(case_id: int, body: CaseStatusIn, user: CurrentUser, db: DB):
    case, role = _get_case(db, user, case_id, allow_admin=False)
    m = case.match
    other_id = m.found_report.user_id if role == "owner" else m.lost_report.user_id
    set_case_status(db, case, body.status, user.id, notify_ids=(other_id,))
    db.commit()
    return _case_out(db, case, role, user)


@router.get("/{case_id}/messages")
def list_messages(case_id: int, user: CurrentUser, db: DB):
    case, role = _get_case(db, user, case_id, allow_admin=False)
    rows = db.scalars(select(Message).where(Message.case_id == case.id).order_by(Message.created_at)).all()
    names = {case.match.lost_report.user_id: case.match.lost_report.owner.name.split(" ")[0],
             case.match.found_report.user_id: case.match.found_report.owner.name.split(" ")[0]}
    return {"messages": [{"id": x.id, "message": x.message, "created_at": x.created_at,
                          "sender_name": names.get(x.sender_id, "User"), "mine": x.sender_id == user.id}
                         for x in rows]}


@router.post("/{case_id}/messages", status_code=201)
def send_message(case_id: int, body: MessageIn, user: CurrentUser, db: DB):
    case, role = _get_case(db, user, case_id, allow_admin=False)
    if case.status == CaseStatus.CLOSED:
        raise conflict("This case is closed")
    msg = Message(case_id=case.id, sender_id=user.id, message=body.message.strip())
    db.add(msg)
    m = case.match
    other_id = m.found_report.user_id if role == "owner" else m.lost_report.user_id
    notify(db, other_id, "new_message", link=f"/cases/{case.id}", item=m.lost_report.name)
    db.commit()
    return {"id": msg.id, "message": msg.message, "created_at": msg.created_at,
            "sender_name": user.name.split(" ")[0], "mine": True}
