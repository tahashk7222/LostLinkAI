"""Orchestrator Agent.

Runs the pipeline for one report:
    Understanding -> embeddings -> Candidate Retrieval -> Matching -> Notification

Failure handling: the report itself is never lost. Any error marks the report's
ai_status FAILED with a generic message, is logged, and can be retried via
POST /reports/{id}/match. The orchestrator only creates MatchCandidates and
notifications; it never grants access to private data.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.ai.config import get_matching_config
from app.ai.matching import score_pair
from app.ai.providers import get_text_embedder
from app.ai.retrieval import retrieve_candidates
from app.ai.understanding import embedding_text, understand
from app.db.session import SessionLocal
from app.models import ItemAttribute, ItemReport, MatchCandidate
from app.models.enums import AIStatus, MatchStatus, ReportStatus, ReportType
from app.services.audit import audit
from app.services.notifications import notify
from app.services.state_machine import transition

logger = logging.getLogger("lostlink.ai")


def analyze_report(db: Session, report: ItemReport):
    """Item Understanding: store attributes + text embedding on the report."""
    u = understand(report)
    db.execute(delete(ItemAttribute).where(ItemAttribute.report_id == report.id))
    for a in u.attributes:
        db.add(ItemAttribute(report_id=report.id, attribute_name=a.name, attribute_value=a.value[:200],
                             source=a.source, confidence=a.confidence))
    report.text_embedding = get_text_embedder().embed(embedding_text(report))
    return u


def run_matching(db: Session, report: ItemReport) -> list[MatchCandidate]:
    """Full pipeline for one report. Returns matches at or above threshold, best first."""
    cfg = get_matching_config()
    ru = analyze_report(db, report)
    db.flush()

    results = []
    for cand in retrieve_candidates(db, report, cfg):
        if cand.text_embedding is None:
            analyze_report(db, cand)
        cu = understand(cand)
        if report.report_type == ReportType.LOST:
            lost, found, lu, fu = report, cand, ru, cu
        else:
            lost, found, lu, fu = cand, report, cu, ru
        results.append((lost, found, score_pair(lost, found, lu, fu, cfg)))

    results.sort(key=lambda r: r[2].score, reverse=True)
    matches: list[MatchCandidate] = []
    for lost, found, res in results[: cfg.max_candidates]:
        existing = db.scalar(select(MatchCandidate).where(
            MatchCandidate.lost_report_id == lost.id, MatchCandidate.found_report_id == found.id))
        if existing:
            if existing.status == MatchStatus.POTENTIAL_MATCH:  # refresh score only before workflow starts
                existing.score, existing.signals, existing.explanation = res.score, res.signals, res.explanation
            if existing.score >= cfg.threshold:
                matches.append(existing)
            continue
        if res.score < cfg.threshold:
            continue
        m = MatchCandidate(lost_report_id=lost.id, found_report_id=found.id, score=res.score,
                           signals=res.signals, explanation=res.explanation)
        db.add(m)
        db.flush()
        matches.append(m)
        for r in (lost, found):
            if r.status == ReportStatus.ACTIVE:
                transition(r, ReportStatus.POTENTIAL_MATCH)
        notify(db, lost.user_id, "match_owner", link=f"/matches/{m.id}", item=lost.name)
        notify(db, found.user_id, "match_finder", link=f"/matches/{m.id}", item=found.name)
        audit(db, "match.created", None, "match", m.id, score=res.score)

    report.ai_status = AIStatus.DONE
    report.ai_error = None
    return sorted(matches, key=lambda m: m.score, reverse=True)


def process_report(report_id: int) -> None:
    """Background entry point with its own DB session and failure isolation."""
    with SessionLocal() as db:
        report = db.scalar(select(ItemReport).options(selectinload(ItemReport.images))
                           .where(ItemReport.id == report_id))
        if report is None:
            return
        try:
            run_matching(db, report)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("AI pipeline failed for report %s", report_id)
            report = db.get(ItemReport, report_id)
            if report is not None:
                report.ai_status = AIStatus.FAILED
                report.ai_error = "Automatic matching failed. You can retry from the report page."
                db.commit()
