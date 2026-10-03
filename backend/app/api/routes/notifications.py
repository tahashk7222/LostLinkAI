from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.core.errors import not_found
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": n.id, "type": n.type, "title": n.title, "message": n.message, "link": n.link,
            "read": n.read, "created_at": n.created_at}


@router.get("")
def list_notifications(user: CurrentUser, db: DB, unread_only: bool = False,
                       limit: Annotated[int, Query(ge=1, le=100)] = 50):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).where(Notification.user_id == user.id, Notification.read.is_(False)))
    return {"notifications": [_out(n) for n in rows], "unread": unread}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: CurrentUser, db: DB):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise not_found("Notification")
    n.read = True
    db.commit()
    return _out(n)


@router.post("/read-all")
def mark_all_read(user: CurrentUser, db: DB):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    db.commit()
    return {"ok": True}
