import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.ai.orchestrator import MATCHING_LOCK, process_report, run_matching
from app.ai.providers import get_image_embedder
from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError, bad_request
from app.models import ItemImage, ItemReport, MatchCandidate
from app.models.enums import AIStatus, MatchStatus, ReportStatus, ReportType
from app.schemas.reports import ImageOut, ReportCreate, ReportUpdate
from app.services import storage
from app.services.audit import audit
from app.services.location import resolve_location
from app.services.match_lifecycle import withdraw_matches
from app.services.matches import match_summary
from app.services.reports import PUBLIC_STATUSES, get_owned, get_viewable, image_url, load_report, serialize
from app.services.state_machine import transition

logger = logging.getLogger("lostlink.reports")

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_IMAGES = 4
EDITABLE_STATUSES = (ReportStatus.DRAFT, ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH)


LOCATION_FIELDS = ("location", "place_key", "location_type", "latitude", "longitude")


@router.post("", status_code=201)
def create_report(body: ReportCreate, user: CurrentUser, db: DB, bg: BackgroundTasks):
    data = body.model_dump(exclude=set(LOCATION_FIELDS))
    loc = resolve_location(body.location, body.place_key, body.latitude, body.longitude, body.location_type)
    r = ItemReport(user_id=user.id, **data, **loc.as_fields())
    db.add(r)
    db.flush()
    audit(db, "report.create", user.id, "report", r.id, type=r.report_type.value)
    db.commit()
    bg.add_task(process_report, r.id)
    return serialize(load_report(db, r.id), user)


@router.get("")
def list_reports(
    user: CurrentUser,
    db: DB,
    mine: bool = False,
    report_type: ReportType | None = None,
    category: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
):
    stmt = select(ItemReport).options(selectinload(ItemReport.images), selectinload(ItemReport.owner),
                                      selectinload(ItemReport.attributes))
    if mine:
        stmt = stmt.where(ItemReport.user_id == user.id)
    else:
        stmt = stmt.where(ItemReport.status.in_(PUBLIC_STATUSES))
    if report_type:
        stmt = stmt.where(ItemReport.report_type == report_type)
    if category:
        stmt = stmt.where(func.lower(ItemReport.category) == category.lower())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ItemReport.name).like(like), func.lower(ItemReport.description).like(like),
                              func.lower(ItemReport.location).like(like), func.lower(ItemReport.category).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ItemReport.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize(r, user) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{report_id}")
def get_report(report_id: int, user: CurrentUser, db: DB):
    return serialize(get_viewable(db, user, report_id), user)


@router.put("/{report_id}")
def update_report(report_id: int, body: ReportUpdate, user: CurrentUser, db: DB, bg: BackgroundTasks):
    r = get_owned(db, user, report_id)
    data = body.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if new_status is not None:
        if new_status != ReportStatus.CLOSED:
            raise bad_request("You can only close your report")
        transition(r, ReportStatus.CLOSED)
        withdraw_matches(db, r, reason="report closed")
    if data:
        if r.status not in EDITABLE_STATUSES:
            raise AppError(409, "This report can no longer be edited")
        loc_changes = {k: data.pop(k) for k in LOCATION_FIELDS if k in data}
        if loc_changes:
            if set(loc_changes) == {"location"} and r.zone is not None:
                # Relabel only: keep the already-validated point.
                data["location"] = loc_changes["location"] or r.location
            else:
                new_point = {"place_key", "latitude", "longitude"} & set(loc_changes)
                loc = resolve_location(
                    loc_changes.get("location", r.location),
                    loc_changes.get("place_key") if new_point else r.place_key,
                    loc_changes.get("latitude") if new_point else r.latitude,
                    loc_changes.get("longitude") if new_point else r.longitude,
                    loc_changes.get("location_type") if new_point else r.location_type,
                )
                data.update(loc.as_fields())
        for k, v in data.items():
            setattr(r, k, v)
        r.ai_status = AIStatus.PENDING
    audit(db, "report.update", user.id, "report", r.id, fields=sorted(data) + (["status"] if new_status else []))
    db.commit()
    if data:
        bg.add_task(process_report, r.id)
    return serialize(load_report(db, r.id), user)


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, user: CurrentUser, db: DB):
    r = get_owned(db, user, report_id)
    if r.status in (ReportStatus.CONNECTED,):
        raise AppError(409, "This report has an open recovery case. Close the case first.")
    paths = [i.storage_path for i in r.images]
    audit(db, "report.delete", user.id, "report", r.id)
    db.delete(r)
    db.commit()
    for p in paths:
        storage.delete_image(p)


@router.post("/{report_id}/images", response_model=ImageOut, status_code=201)
async def upload_image(report_id: int, user: CurrentUser, db: DB, bg: BackgroundTasks,
                       file: Annotated[UploadFile, File()]):
    r = get_owned(db, user, report_id)
    if len(r.images) >= MAX_IMAGES:
        raise bad_request(f"A report can have at most {MAX_IMAGES} photos")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    path, meta, img = storage.save_image(data, file.content_type)
    try:
        features = get_image_embedder().embed(img)
    except Exception as exc:
        # Logged so a missing visual signal is visible in server logs. Matching still works without it.
        logger.warning("image embedding failed for report %s: %s", r.id, exc.__class__.__name__)
        features = None
    image = ItemImage(report_id=r.id, storage_path=path, content_type="image/jpeg", meta=meta, embedding=features)
    db.add(image)
    r.ai_status = AIStatus.PENDING
    audit(db, "report.image_upload", user.id, "report", r.id)
    db.commit()
    bg.add_task(process_report, r.id)
    return ImageOut(id=image.id, url=image_url(image.id))


@router.delete("/{report_id}/images/{image_id}", status_code=204)
def delete_image(report_id: int, image_id: int, user: CurrentUser, db: DB):
    r = get_owned(db, user, report_id)
    image = next((i for i in r.images if i.id == image_id), None)
    if image is None:
        raise AppError(404, "Image not found")
    path = image.storage_path
    db.delete(image)
    db.commit()
    storage.delete_image(path)


@router.post("/{report_id}/match")
def match_now(report_id: int, user: CurrentUser, db: DB):
    """Run (or retry) the AI matching pipeline synchronously for the owner's report."""
    r = get_owned(db, user, report_id)
    if r.status not in PUBLIC_STATUSES:
        raise AppError(409, "Matching only runs for open reports")
    with MATCHING_LOCK:
        try:
            matches = run_matching(db, r)
            db.commit()
        except Exception:
            db.rollback()
            r = db.get(ItemReport, report_id)
            r.ai_status = AIStatus.FAILED
            r.ai_error = "Automatic matching failed. Please try again later."
            db.commit()
            raise AppError(503, "Matching is temporarily unavailable. Your report is saved; please retry later.")
    return {"matches": [match_summary(db, m, user) for m in matches]}


@router.get("/{report_id}/matches")
def report_matches(report_id: int, user: CurrentUser, db: DB):
    r = get_owned(db, user, report_id)
    col = MatchCandidate.lost_report_id if r.report_type == ReportType.LOST else MatchCandidate.found_report_id
    rows = db.scalars(select(MatchCandidate).where(col == r.id, MatchCandidate.status != MatchStatus.DISMISSED)
                      .order_by(MatchCandidate.score.desc())).all()
    return {"ai_status": r.ai_status, "ai_error": r.ai_error, "matches": [match_summary(db, m, user) for m in rows]}
