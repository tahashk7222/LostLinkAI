from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.config import get_matching_config
from app.core.errors import not_found
from app.models import Case, ItemReport, MatchCandidate, User, Verification
from app.models.enums import Role
from app.services.reports import load_report, to_public

DISCLAIMER = ("This is a potential match suggested by LostLink AI based on similarity. "
              "It is not proof of ownership; ownership must be verified by people.")


def role_in_match(user: User, m: MatchCandidate) -> str | None:
    if m.lost_report.user_id == user.id:
        return "owner"
    if m.found_report.user_id == user.id:
        return "finder"
    if user.role == Role.ADMIN:
        return "admin"
    return None


def get_match_for(db: Session, user: User, match_id: int, roles: tuple[str, ...] = ("owner", "finder", "admin")):
    m = db.get(MatchCandidate, match_id)
    if m is None:
        raise not_found("Match")
    role = role_in_match(user, m)
    if role not in roles:
        raise not_found("Match")
    return m, role


def confidence_label(score: float) -> str:
    cfg = get_matching_config()
    return "HIGH" if score >= cfg.high_confidence else "MEDIUM" if score >= cfg.threshold else "LOW"


def match_summary(db: Session, m: MatchCandidate, user: User) -> dict:
    role = role_in_match(user, m)
    if role == "owner":
        mine, other = m.lost_report_id, m.found_report_id
    elif role == "finder":
        mine, other = m.found_report_id, m.lost_report_id
    else:
        mine, other = None, None
    case = db.scalar(select(Case).where(Case.match_id == m.id))
    verification = db.scalar(select(Verification).where(Verification.match_id == m.id)
                             .order_by(Verification.id.desc()))
    out = {
        "id": m.id,
        "score": m.score,
        "score_percent": round(m.score * 100),
        "confidence": confidence_label(m.score),
        "explanation": m.explanation,
        "evidence": m.evidence or [],
        "lead": m.lead_label,  # STRONG | POSSIBLE | WEAK; null for suggestions created before scoring v2
        "signals": m.signals,
        "status": m.status,
        "my_role": role,
        "my_report_id": mine,
        "case_id": case.id if case else None,
        "verification_status": verification.result if verification else None,
        "disclaimer": DISCLAIMER,
        "created_at": m.created_at,
    }
    if other is not None:
        out["other_report"] = to_public(load_report(db, other), user)
    else:  # admin oversight
        out["lost_report"] = to_public(load_report(db, m.lost_report_id), user)
        out["found_report"] = to_public(load_report(db, m.found_report_id), user)
    return out


def item_name(db: Session, report_id: int) -> str:
    r = db.get(ItemReport, report_id)
    return r.name if r else "your item"
