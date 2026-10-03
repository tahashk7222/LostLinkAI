"""Admin oversight. Admins see what moderation needs, not private details
(private_details, exact coordinates and message contents are not exposed here)."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.deps import DB, AdminUser
from app.core.errors import bad_request, not_found
from app.models import AuditLog, Case, Flag, ItemReport, MatchCandidate, User
from app.models.enums import AIStatus, FlagStatus, ReportStatus, Role
from app.services.audit import audit
from app.services.matches import match_summary
from app.services.notifications import notify
from app.services.reports import load_report, to_public
from app.services.state_machine import transition

router = APIRouter(prefix="/admin", tags=["admin"])


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
