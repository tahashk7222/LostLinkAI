"""Report access rules and serialisation (public vs. owner views)."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import forbidden, not_found
from app.core.security import create_image_token
from app.models import ItemReport, MatchCandidate, User
from app.models.enums import ReportStatus, Role
from app.schemas.reports import AttributeOut, ImageOut, ReportPrivate, ReportPublic

PUBLIC_STATUSES = (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH)


def load_report(db: Session, report_id: int) -> ItemReport:
    r = db.scalar(select(ItemReport)
                  .options(selectinload(ItemReport.images), selectinload(ItemReport.attributes),
                           selectinload(ItemReport.owner))
                  .where(ItemReport.id == report_id))
    if r is None:
        raise not_found("Report")
    return r


def is_match_party(db: Session, user: User, report: ItemReport) -> bool:
    """True if the user owns a report that is matched with this report."""
    q = select(MatchCandidate.id).join(
        ItemReport,
        or_(ItemReport.id == MatchCandidate.lost_report_id, ItemReport.id == MatchCandidate.found_report_id),
    ).where(
        or_(MatchCandidate.lost_report_id == report.id, MatchCandidate.found_report_id == report.id),
        ItemReport.user_id == user.id,
    )
    return db.scalar(q.limit(1)) is not None


def can_view(db: Session, user: User, report: ItemReport) -> bool:
    if report.user_id == user.id or user.role == Role.ADMIN:
        return True
    if report.status in PUBLIC_STATUSES:
        return True
    return report.status != ReportStatus.DEACTIVATED and is_match_party(db, user, report)


def get_viewable(db: Session, user: User, report_id: int) -> ItemReport:
    r = load_report(db, report_id)
    if not can_view(db, user, r):
        raise not_found("Report")  # don't reveal existence
    return r


def get_owned(db: Session, user: User, report_id: int) -> ItemReport:
    r = load_report(db, report_id)
    if r.user_id != user.id:
        raise forbidden("Only the person who created this report can change it")
    return r


def image_url(image_id: int) -> str:
    return f"/images/{image_id}?token={create_image_token(image_id)}"


def _images(r: ItemReport) -> list[ImageOut]:
    return [ImageOut(id=i.id, url=image_url(i.id)) for i in r.images]


def to_public(r: ItemReport, viewer: User | None = None) -> ReportPublic:
    return ReportPublic(
        id=r.id, report_type=r.report_type, category=r.category, name=r.name, description=r.description,
        color=r.color, brand=r.brand, model=r.model, distinctive_features=r.distinctive_features,
        date_time=r.date_time, location=r.location,
        # ~1 km precision for everyone except the author
        approx_latitude=round(r.latitude, 2) if r.latitude is not None else None,
        approx_longitude=round(r.longitude, 2) if r.longitude is not None else None,
        status=r.status, created_at=r.created_at, reporter_name=r.owner.name.split(" ")[0],
        images=_images(r), is_owner=bool(viewer and viewer.id == r.user_id),
    )


def to_private(r: ItemReport) -> ReportPrivate:
    base = to_public(r).model_dump()
    base["is_owner"] = True
    return ReportPrivate(
        **base, private_details=r.private_details, latitude=r.latitude, longitude=r.longitude,
        ai_status=r.ai_status, ai_error=r.ai_error,
        attributes=[AttributeOut.model_validate(a) for a in r.attributes],
    )


def serialize(r: ItemReport, viewer: User):
    return to_private(r) if viewer.id == r.user_id else to_public(r, viewer)
