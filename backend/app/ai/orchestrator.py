"""Orchestrator Agent.

Runs the pipeline for one report:
    Understanding -> embeddings -> Candidate Retrieval -> Matching -> Notification

Failure handling: the report itself is never lost. Any error marks the report's
ai_status FAILED with a generic message, is logged, and can be retried via
POST /reports/{id}/match. The orchestrator only creates MatchCandidates and
notifications; it never grants access to private data.
"""

import logging
import threading

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
from app.services.match_lifecycle import OPEN_MATCH, withdraw_matches
from app.services.notifications import notify
from app.services.state_machine import transition

logger = logging.getLogger("lostlink.ai")

# Serialises matching runs within this process, including the commit. Two runs for overlapping
# reports would otherwise race on the same candidate pairs. Multi-process deployments need a
# database-level lock instead (see README limitations).
MATCHING_LOCK = threading.RLock()

OPEN_REPORT_STATUSES = (ReportStatus.ACTIVE, ReportStatus.POTENTIAL_MATCH)


def analyze_report(db: Session, report: ItemReport):
    """Item Understanding: store attributes + text embedding on the report."""
    u = understand(report)
    db.execute(delete(ItemAttribute).where(ItemAttribute.report_id == report.id))
    for a in u.attributes:
        db.add(ItemAttribute(report_id=report.id, attribute_name=a.name, attribute_value=a.value[:200],
                             source=a.source, confidence=a.confidence))
    report.text_embedding = get_text_embedder().embed(embedding_text(report))
    return u


def score_candidates(db: Session, report: ItemReport, cfg=None) -> list[tuple[ItemReport, ItemReport, object]]:
    """Understanding -> retrieval -> scoring for one report. Returns (lost, found, result), best first.

    Shared by the live pipeline and the offline evaluation harness (backend/evaluation)."""
    cfg = cfg or get_matching_config()
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
    return results


def select_new_matches(results, cfg=None):
    """Which scored pairs would become (notified) match candidates in a fresh database."""
    cfg = cfg or get_matching_config()
    return [r for r in results[: cfg.max_candidates] if r[2].score >= cfg.threshold]


def run_matching(db: Session, report: ItemReport) -> list[MatchCandidate]:
    """Reconcile the report's suggestions with the current scores.

    Creates new suggestions at or above threshold, refreshes uncontested ones, and withdraws
    uncontested ones that no longer qualify. Returns open matches, best first.
    Callers hold MATCHING_LOCK and commit.
    """
    cfg = get_matching_config()
    if report.status not in OPEN_REPORT_STATUSES:
        # Closed or moderated while queued: no new suggestions, and withdraw any old ones.
        withdraw_matches(db, report, reason="report is no longer open")
        report.ai_status, report.ai_error = AIStatus.DONE, None
        return []

    results = score_candidates(db, report, cfg)
    current = {(lost.id, found.id): (lost, found, res) for lost, found, res in select_new_matches(results, cfg)}
    withdraw_matches(db, report, keep=set(current), reason="no longer a candidate")

    matches: list[MatchCandidate] = []
    for (lost_id, found_id), (lost, found, res) in current.items():
        existing = db.scalar(select(MatchCandidate).where(
            MatchCandidate.lost_report_id == lost_id, MatchCandidate.found_report_id == found_id))
        if existing is not None:
            if existing.status == MatchStatus.POTENTIAL_MATCH:  # refresh only before the workflow starts
                existing.score, existing.signals, existing.explanation = res.score, res.signals, res.explanation
                existing.evidence = res.evidence
            if existing.status in OPEN_MATCH:
                matches.append(existing)
            continue  # dismissed, rejected or verified pairs are never re-suggested or re-notified
        m = MatchCandidate(lost_report_id=lost.id, found_report_id=found.id, score=res.score,
                           signals=res.signals, explanation=res.explanation, evidence=res.evidence)
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
    with MATCHING_LOCK, SessionLocal() as db:
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
