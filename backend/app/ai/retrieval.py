"""Candidate Retrieval: structured filtering, then vector ranking.

Filters by opposite report type, active status, different reporter, compatible
category group, time window and (when coordinates exist) distance. Remaining
candidates are pre-ranked by text-embedding similarity. At regional MVP scale this
runs in Python; with Postgres the ranking can move to pgvector without changing callers.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.config import MatchingConfig
from app.ai.matching import as_utc, haversine_km
from app.ai.providers import cosine
from app.ai.understanding import normalize_category
from app.models import ItemReport
from app.models.enums import ReportStatus, ReportType

OPEN_STATUSES = (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH)


def report_group(r) -> str:
    return normalize_category(f"{r.category} {r.name}")[1]


def retrieve_candidates(db: Session, report: ItemReport, cfg: MatchingConfig, limit: int = 50) -> list[ItemReport]:
    opposite = ReportType.FOUND if report.report_type == ReportType.LOST else ReportType.LOST
    rows = db.scalars(
        select(ItemReport)
        .options(selectinload(ItemReport.images))
        .where(
            ItemReport.report_type == opposite,
            ItemReport.status.in_(OPEN_STATUSES),
            ItemReport.user_id != report.user_id,
        )
    ).all()

    group = report_group(report)
    slack = timedelta(hours=cfg.time_slack_hours)
    window = timedelta(days=cfg.max_days_after_loss)

    out = []
    for cand in rows:
        cand_group = report_group(cand)
        if group != "other" and cand_group != "other" and cand_group != group:
            continue
        lost, found = (report, cand) if report.report_type == ReportType.LOST else (cand, report)
        lt, ft = as_utc(lost.date_time), as_utc(found.date_time)
        if not (lt - slack <= ft <= lt + window):
            continue
        if None not in (report.latitude, report.longitude, cand.latitude, cand.longitude):
            if haversine_km(report.latitude, report.longitude, cand.latitude, cand.longitude) > cfg.max_distance_km:
                continue
        out.append(cand)

    out.sort(key=lambda c: cosine(report.text_embedding, c.text_embedding), reverse=True)
    return out[:limit]
