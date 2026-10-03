from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    action: str,
    actor_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    **meta,
) -> None:
    """Record a security-relevant action. Caller commits. Never put secrets in meta."""
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, meta=meta or None))
