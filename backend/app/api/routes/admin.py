"""Admin oversight. Admins see what moderation needs, not private details
(private_details, exact coordinates and message contents are not exposed here)."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from app.ai.retrieval import OPEN_STATUSES
from app.api.deps import DB, AdminUser
from app.core.errors import bad_request, not_found
from app.models import AuditLog, Case, Flag, ItemReport, MatchCandidate, User, Verification
from app.models.enums import AIStatus, CaseStatus, FlagStatus, MatchStatus, ReportStatus, ReportType, Role
from app.schemas.admin import RejectIn
from app.services.audit import audit
from app.services.case_lifecycle import set_case_status
from app.services.match_lifecycle import withdraw_matches
from app.services.matches import match_summary
from app.services.moderation import approve_report, reject_report
from app.services.notifications import notify
from app.services.reports import PUBLIC_STATUSES, load_report, to_public
from app.services.state_machine import transition

router = APIRouter(prefix="/admin", tags=["admin"])

# Verification results shown to admins. The answers and advisory notes are never returned by admin routes.
VERIFICATION_DISPLAY = {"PENDING": "pending", "SUBMITTED": "in_progress", "ACCEPTED": "verified", "REJECTED": "failed"}


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


@router.get("/stats")
def stats(_: AdminUser, db: DB):
    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery()))  # noqa: E731
    by_status = dict(db.execute(select(ItemReport.status, func.count()).group_by(ItemReport.status)).all())
    by_type = dict(db.execute(select(ItemReport.report_type, func.count()).group_by(ItemReport.report_type)).all())
    return {
        "users": count(select(User.id)),
        "reports_by_status": {k.value: v for k, v in by_status.items()},
        "reports_by_type": {k.value: v for k, v in by_type.items()},
        "matches": count(select(MatchCandidate.id)),
        "cases": count(select(Case.id)),
        "open_flags": count(select(Flag.id).where(Flag.status == FlagStatus.OPEN)),
        "ai_failures": count(select(ItemReport.id).where(ItemReport.ai_status == AIStatus.FAILED)),
        "failed_logins_recent": count(select(AuditLog.id).where(AuditLog.action == "user.login_failed")),
    }


@router.get("/reports")
def reports(_: AdminUser, db: DB, q: Annotated[str | None, Query(max_length=100)] = None,
            status: ReportStatus | None = None, page: Annotated[int, Query(ge=1)] = 1):
    stmt = select(ItemReport)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ItemReport.name).like(like), func.lower(ItemReport.description).like(like),
                              func.lower(ItemReport.location).like(like)))
    if status:
        stmt = stmt.where(ItemReport.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ItemReport.created_at.desc()).offset((page - 1) * 20).limit(20)).all()
    items = []
    for r in rows:
        d = to_public(load_report(db, r.id)).model_dump()
        d.update(ai_status=r.ai_status, user_id=r.user_id)
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": 20}


@router.post("/reports/{report_id}/deactivate")
def deactivate_report(report_id: int, admin: AdminUser, db: DB):
    r = db.get(ItemReport, report_id)
    if r is None:
        raise not_found("Report")
    transition(r, ReportStatus.DEACTIVATED)
    withdraw_matches(db, r, reason="report deactivated")
    notify(db, r.user_id, "report_deactivated", link=f"/reports/{r.id}", item=r.name)
    audit(db, "admin.report_deactivated", admin.id, "report", r.id)
    db.commit()
    return {"id": r.id, "status": r.status}


@router.post("/reports/{report_id}/reactivate")
def reactivate_report(report_id: int, admin: AdminUser, db: DB):
    r = db.get(ItemReport, report_id)
    if r is None:
        raise not_found("Report")
    if r.status != ReportStatus.DEACTIVATED:
        raise bad_request("Report is not deactivated")
    transition(r, ReportStatus.ACTIVE)
    audit(db, "admin.report_reactivated", admin.id, "report", r.id)
    db.commit()
    return {"id": r.id, "status": r.status}


@router.get("/users")
def users(_: AdminUser, db: DB, q: Annotated[str | None, Query(max_length=100)] = None):
    stmt = select(User)
    if q:
        stmt = stmt.where(func.lower(User.name).like(f"%{q.lower()}%"))
    rows = db.scalars(stmt.order_by(User.created_at.desc()).limit(100)).all()
    report_counts = dict(db.execute(select(ItemReport.user_id, func.count()).group_by(ItemReport.user_id)).all())
    flag_counts = dict(db.execute(select(Flag.entity_id, func.count())
                                  .where(Flag.entity_type == "user").group_by(Flag.entity_id)).all())
    return {"users": [{"id": u.id, "name": u.name, "email": mask_email(u.email), "role": u.role,
                       "is_active": u.is_active, "created_at": u.created_at,
                       "reports": report_counts.get(u.id, 0), "flags": flag_counts.get(u.id, 0)} for u in rows]}


@router.post("/users/{user_id}/{action}")
def moderate_user(user_id: int, action: str, admin: AdminUser, db: DB):
    if action not in ("deactivate", "activate"):
        raise not_found("Action")
    u = db.get(User, user_id)
    if u is None:
        raise not_found("User")
    if u.id == admin.id or u.role == Role.ADMIN:
        raise bad_request("Admins cannot be deactivated here")
    u.is_active = action == "activate"
    audit(db, f"admin.user_{action}d", admin.id, "user", u.id)
    db.commit()
    return {"id": u.id, "is_active": u.is_active}


@router.get("/flags")
def flags(_: AdminUser, db: DB, status: FlagStatus | None = FlagStatus.OPEN):
    stmt = select(Flag)
    if status:
        stmt = stmt.where(Flag.status == status)
    rows = db.scalars(stmt.order_by(Flag.created_at.desc()).limit(100)).all()
    return {"flags": [{"id": f.id, "entity_type": f.entity_type, "entity_id": f.entity_id, "reason": f.reason,
                       "status": f.status, "reporter_id": f.reporter_id, "created_at": f.created_at} for f in rows]}


@router.post("/flags/{flag_id}/{action}")
def resolve_flag(flag_id: int, action: str, admin: AdminUser, db: DB):
    if action not in ("resolve", "dismiss"):
        raise not_found("Action")
    f = db.get(Flag, flag_id)
    if f is None:
        raise not_found("Flag")
    f.status = FlagStatus.RESOLVED if action == "resolve" else FlagStatus.DISMISSED
    audit(db, f"admin.flag_{action}d", admin.id, "flag", f.id)
    db.commit()
    return {"id": f.id, "status": f.status}


@router.get("/cases")
def cases(admin: AdminUser, db: DB):
    rows = db.scalars(select(Case).order_by(Case.updated_at.desc()).limit(100)).all()
    return {"cases": [{"id": c.id, "status": c.status, "created_at": c.created_at, "updated_at": c.updated_at,
                       "match": match_summary(db, c.match, admin)} for c in rows]}


@router.get("/matches")
def matches(admin: AdminUser, db: DB):
    rows = db.scalars(select(MatchCandidate).order_by(MatchCandidate.created_at.desc()).limit(100)).all()
    return {"matches": [match_summary(db, m, admin) for m in rows]}


@router.get("/audit")
def audit_log(_: AdminUser, db: DB, action: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    rows = db.scalars(stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)).all()
    return {"entries": [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "entity_type": a.entity_type,
                         "entity_id": a.entity_id, "meta": a.meta, "timestamp": a.timestamp} for a in rows]}


# ---- Portal: dashboard, report review, verification and recovery monitoring -------------------------------

def _count(db, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery()))


def _audit_out(a: AuditLog) -> dict:
    return {"id": a.id, "actor_id": a.actor_id, "action": a.action, "entity_type": a.entity_type,
            "entity_id": a.entity_id, "meta": a.meta, "timestamp": a.timestamp}


@router.get("/dashboard")
def dashboard(admin: AdminUser, db: DB):
    """Operational cards and recent activity, all computed from stored data."""
    base = stats(admin, db)
    open_flags_on_reports = _count(db, select(Flag.id).where(
        Flag.status == FlagStatus.OPEN, Flag.entity_type == "report"))
    cards = {
        "active_lost": _count(db, select(ItemReport.id).where(
            ItemReport.report_type == ReportType.LOST, ItemReport.status.in_(OPEN_STATUSES))),
        "active_found": _count(db, select(ItemReport.id).where(
            ItemReport.report_type == ReportType.FOUND, ItemReport.status.in_(OPEN_STATUSES))),
        "potential_matches": _count(db, select(MatchCandidate.id).where(
            MatchCandidate.status == MatchStatus.POTENTIAL_MATCH)),
        "verification_open": _count(db, select(Verification.id).where(
            Verification.result.in_(("PENDING", "SUBMITTED")))),
        "recovery_pending": _count(db, select(Case.id).where(Case.status == CaseStatus.CONNECTED)),
        "recovered": _count(db, select(ItemReport.id).where(ItemReport.status == ReportStatus.RECOVERED)),
        "rejected": _count(db, select(ItemReport.id).where(
            ItemReport.status == ReportStatus.DEACTIVATED, ItemReport.moderation_reason.is_not(None))),
        "open_flags_on_reports": open_flags_on_reports,
    }
    recent_reports = db.scalars(select(ItemReport).order_by(ItemReport.created_at.desc()).limit(8)).all()
    recent_matches = db.scalars(select(MatchCandidate).order_by(MatchCandidate.created_at.desc()).limit(8)).all()
    recent_actions = db.scalars(select(AuditLog).where(
        or_(AuditLog.action.like("admin.%"), AuditLog.action.like("item.%"), AuditLog.action.like("case.%")))
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(10)).all()
    return {
        "cards": cards,
        "totals": {"users": base["users"], "matches": base["matches"], "cases": base["cases"],
                   "open_flags": base["open_flags"]},
        "reports_by_status": base["reports_by_status"],
        "recent_reports": [{"id": r.id, "report_type": r.report_type, "name": r.name, "status": r.status,
                            "zone": r.zone, "created_at": r.created_at} for r in recent_reports],
        "recent_matches": [{"id": m.id, "status": m.status, "lead": m.lead_label,
                            "relevance_percent": round(m.score * 100), "created_at": m.created_at}
                           for m in recent_matches],
        "recent_actions": [_audit_out(a) for a in recent_actions],
    }


@router.get("/reports/{report_id}")
def report_detail(report_id: int, _: AdminUser, db: DB):
    """Moderation view of one report. No private details, exact coordinates or verification data."""
    if db.get(ItemReport, report_id) is None:
        raise not_found("Report")
    r = load_report(db, report_id)
    matches = db.scalars(select(MatchCandidate).where(
        or_(MatchCandidate.lost_report_id == r.id, MatchCandidate.found_report_id == r.id))
        .order_by(MatchCandidate.created_at.desc())).all()
    return {
        **to_public(r).model_dump(),
        "user_id": r.user_id,
        "reporter_email": mask_email(r.owner.email),
        "ai_status": r.ai_status,
        "attributes": [{"name": a.attribute_name, "value": a.attribute_value, "source": a.source}
                       for a in r.attributes],
        "moderation": {"reason": r.moderation_reason, "note": r.moderation_note,
                       "moderated_by": r.moderated_by, "moderated_at": r.moderated_at},
        "archived_at": r.archived_at,
        "matches": [{"id": m.id, "status": m.status, "lead": m.lead_label,
                     "relevance_percent": round(m.score * 100),
                     "case_id": db.scalar(select(Case.id).where(Case.match_id == m.id))}
                    for m in matches],
    }


@router.post("/reports/{report_id}/approve")
def approve(report_id: int, admin: AdminUser, db: DB):
    r = db.get(ItemReport, report_id)
    if r is None:
        raise not_found("Report")
    approve_report(db, admin, r)
    db.commit()
    return {"id": r.id, "status": r.status, "moderated_at": r.moderated_at}


@router.post("/reports/{report_id}/reject")
def reject(report_id: int, body: RejectIn, admin: AdminUser, db: DB):
    r = db.get(ItemReport, report_id)
    if r is None:
        raise not_found("Report")
    reject_report(db, admin, r, body.reason, body.note)
    db.commit()
    return {"id": r.id, "status": r.status, "reason": r.moderation_reason}


@router.get("/verification")
def verification(_: AdminUser, db: DB):
    """Ownership verification progress only. Questions, answers and advisory notes are never returned."""
    rows = db.execute(select(Verification, MatchCandidate.status)
                      .join(MatchCandidate, Verification.match_id == MatchCandidate.id)
                      .order_by(Verification.created_at.desc()).limit(100)).all()
    out = []
    for v, match_status in rows:
        display = "cancelled" if match_status == MatchStatus.DISMISSED else VERIFICATION_DISPLAY.get(v.result, "pending")
        out.append({"id": v.id, "match_id": v.match_id, "match_status": match_status, "display_status": display,
                    "created_at": v.created_at, "submitted_at": v.submitted_at, "decided_at": v.decided_at})
    return {"verifications": out}


def _recovery_item(r: ItemReport) -> dict:
    return {"id": r.id, "report_type": r.report_type, "name": r.name, "status": r.status,
            "active_listing": r.status in PUBLIC_STATUSES,
            "matching_eligible": r.status in OPEN_STATUSES,
            "archived": r.archived_at is not None, "archived_at": r.archived_at}


@router.get("/cases/{case_id}")
def case_detail(case_id: int, admin: AdminUser, db: DB):
    c = db.get(Case, case_id)
    if c is None:
        raise not_found("Case")
    m = c.match
    latest = db.scalar(select(Verification).where(Verification.match_id == m.id).order_by(Verification.id.desc()))
    actions = db.scalars(select(AuditLog).where(or_(
        and_(AuditLog.entity_type == "case", AuditLog.entity_id == c.id),
        and_(AuditLog.entity_type == "report", AuditLog.entity_id.in_((m.lost_report_id, m.found_report_id))),
    )).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(20)).all()
    return {
        "id": c.id, "status": c.status, "created_at": c.created_at, "updated_at": c.updated_at,
        "match": match_summary(db, m, admin),
        "lost": _recovery_item(m.lost_report), "found": _recovery_item(m.found_report),
        "verification_status": VERIFICATION_DISPLAY.get(latest.result, "pending") if latest else None,
        "recovery_confirmed": c.status in (CaseStatus.RECOVERED, CaseStatus.CLOSED),
        "actions": [_audit_out(a) for a in actions],
    }


@router.post("/cases/{case_id}/close")
def close_case(case_id: int, admin: AdminUser, db: DB):
    c = db.get(Case, case_id)
    if c is None:
        raise not_found("Case")
    m = c.match
    set_case_status(db, c, CaseStatus.CLOSED, admin.id,
                    notify_ids=(m.lost_report.user_id, m.found_report.user_id), audit_action="admin.case_closed")
    db.commit()
    return {"id": c.id, "status": c.status}
