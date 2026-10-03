from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.core.errors import bad_request, not_found
from app.models import Flag, ItemReport, User
from app.schemas.workflow import FlagIn
from app.services.audit import audit

router = APIRouter(prefix="/flags", tags=["moderation"])


@router.post("", status_code=201)
def create_flag(body: FlagIn, user: CurrentUser, db: DB):
    """Let any user report an inappropriate report or user for admin review."""
    target = db.get(ItemReport if body.entity_type == "report" else User, body.entity_id)
    if target is None:
        raise not_found("Item")
    if body.entity_type == "user" and body.entity_id == user.id:
        raise bad_request("You cannot report yourself")
    f = Flag(reporter_id=user.id, entity_type=body.entity_type, entity_id=body.entity_id, reason=body.reason.strip())
    db.add(f)
    db.flush()
    audit(db, "flag.created", user.id, body.entity_type, body.entity_id, flag_id=f.id)
    db.commit()
    return {"id": f.id, "status": f.status}
