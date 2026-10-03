"""Offline evaluation of the matching pipeline on the SYNTHETIC lost/found dataset.

Each lost report is used as a query against every found report in the dataset.
Scoring goes through the same code the live pipeline uses (retrieval, understanding,
score_pair, select_new_matches), in a throwaway database.

Metrics (all on the synthetic dataset; they describe this dataset, not real-world accuracy):
  precision@1         queries with a true match whose top-ranked candidate is that match
  recall@threshold    true pairs that would be notified (score >= threshold, within max_candidates)
  false-positive rate notified pairs that are not true matches, divided by all non-matching pairs
  FPR (hard)          the same, restricted to the hard negatives built for each query

    python -m evaluation.run_eval --label baseline
"""

import argparse
import json
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.config import MatchingConfig, get_matching_config
from app.ai.orchestrator import analyze_report, score_candidates, select_new_matches
from app.db.session import Base
from app.models import ItemReport, User  # noqa: F401  (registers tables on Base.metadata)
from app.models.enums import ReportStatus, ReportType

HERE = Path(__file__).resolve().parent
DATASET = HERE / "data" / "synthetic_pairs.json"
RESULTS = HERE / "results"

REPORT_COLUMNS = ("name", "category", "description", "color", "brand", "distinctive_features",
                  "private_details", "location", "location_type", "place_key", "latitude", "longitude", "zone")


def _to_report(row: dict, user_id: int, report_type: ReportType) -> ItemReport:
    fields = {k: row[k] for k in REPORT_COLUMNS if k in row}
    when = datetime.fromisoformat(row["date_time"].replace("Z", "+00:00"))
    return ItemReport(user_id=user_id, report_type=report_type, date_time=when,
                      status=ReportStatus.ACTIVE, **fields)


def load_dataset(path: Path = DATASET) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("dataset") != "SYNTHETIC":
        raise ValueError("evaluation expects the SYNTHETIC dataset label")
    return data


def populate(db: Session, data: dict) -> tuple[dict[str, ItemReport], dict[int, str]]:
    """Insert the dataset. Returns {external id: report} and {db id: external id}."""
    owner = User(name="Query owner", email="owner@eval.invalid", password_hash="unused")
    finder = User(name="Finder", email="finder@eval.invalid", password_hash="unused")
    db.add_all([owner, finder])
    db.flush()

    by_ext: dict[str, ItemReport] = {}
    for row in data["lost"]:
        r = _to_report(row, owner.id, ReportType.LOST)
        db.add(r)
        by_ext[row["id"]] = r
    for row in data["found"]:
        r = _to_report(row, finder.id, ReportType.FOUND)
        db.add(r)
        by_ext[row["id"]] = r
    db.flush()
    for row in data["found"]:  # analysed on creation, as in production
        analyze_report(db, by_ext[row["id"]])
    db.flush()
    ext_of = {r.id: ext for ext, r in by_ext.items()}
    return by_ext, ext_of


def _fp_type(row: dict, query_id: str) -> str:
    """Label a false positive by where the found report came from, relative to this query."""
    if row.get("role") == "hard_negative" and row.get("origin") == query_id:
        return f"hard:{row['negative_type']}"  # built to look like this query's item
    if row.get("role") == "easy_negative":
        return "unrelated"
    if row.get("role") == "true_match":
        return "other_query_true_match"  # genuine match for a different lost item
    return "other_query_hard_negative"


def evaluate(data: dict, db: Session, cfg: MatchingConfig | None = None) -> dict:
    cfg = cfg or get_matching_config()
    started = time.perf_counter()
    by_ext, ext_of = populate(db, data)

    truth = {tuple(p) for p in data["true_pairs"]}
    found_ids = [f["id"] for f in data["found"]]
    role = {f["id"]: f for f in data["found"]}
    hard_for = {}  # lost id -> set of hard-negative found ids
    for f in data["found"]:
        if f.get("role") == "hard_negative":
            hard_for.setdefault(f["origin"], set()).add(f["id"])

    p1_hits = p1_queries = 0
    retrieved_true = notified_true = notified_total = 0
    fp_total = fp_hard = 0
    hard_total = sum(len(s) for s in hard_for.values())
    queries_with_fp = 0
    fp_by_type: Counter = Counter()
    examples = []

    for lrow in data["lost"]:
        lid = lrow["id"]
        results = score_candidates(db, by_ext[lid], cfg)
        ranked = [(ext_of[f.id], res) for _, f, res in results]
        notified_ids = {ext_of[f.id] for _, f, _ in select_new_matches(results, cfg)}

        true_f = {f for (l, f) in truth if l == lid}
        if true_f:
            p1_queries += 1
            if ranked and ranked[0][0] in true_f:
                p1_hits += 1
            retrieved_true += len(true_f & {e for e, _ in ranked})
            notified_true += len(true_f & notified_ids)

        notified_total += len(notified_ids)
        false_notes = notified_ids - true_f
        fp_total += len(false_notes)
        fp_hard += len(false_notes & hard_for.get(lid, set()))
        if false_notes:
            queries_with_fp += 1
        for ext, res in ranked:
            if ext in false_notes:
                ntype = _fp_type(role[ext], lid)
                fp_by_type[ntype] += 1
                examples.append({
                    "query": lid, "found": ext, "negative_type": ntype, "score": res.score,
                    "explanation": res.explanation,
                })

    n_true = len(truth)
    n_queries = len(data["lost"])
    negatives = n_queries * len(found_ids) - n_true
    examples.sort(key=lambda e: e["score"], reverse=True)

    def ratio(a, b):
        return round(a / b, 3) if b else None

    return {
        "queries": n_queries,
        "found_reports": len(found_ids),
        "true_pairs": n_true,
        "hard_negative_pairs": hard_total,
        "metrics": {
            "precision_at_1": ratio(p1_hits, p1_queries),
            "recall_retrieved": ratio(retrieved_true, n_true),
            "recall_at_threshold": ratio(notified_true, n_true),
            "false_positive_rate_all_negatives": ratio(fp_total, negatives),
            "false_positive_rate_hard_negatives": ratio(fp_hard, hard_total),
            "precision_of_notifications": ratio(notified_true, notified_total),
            "notifications_per_query": ratio(notified_total, n_queries),
            "queries_with_false_notification": ratio(queries_with_fp, n_queries),
        },
        "counts": {
            "true_notified": notified_true,
            "notified_total": notified_total,
            "false_notified": fp_total,
            "false_notified_hard": fp_hard,
            "false_notified_by_type": dict(fp_by_type),
        },
        "false_positive_examples": examples[:10],
        "runtime_seconds": round(time.perf_counter() - started, 2),
    }


def run(label: str) -> dict:
    cfg = get_matching_config()
    data = load_dataset()
    with tempfile.TemporaryDirectory(prefix="lostlink-eval-") as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'eval.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            result = evaluate(data, db, cfg)
        engine.dispose()
    result.update(
        label=label,
        dataset={"name": data["dataset"], "generator": data["generator"], "seed": data["seed"],
                 "notice": data["notice"]},
        config={"threshold": cfg.threshold, "max_candidates": cfg.max_candidates,
                "weights": cfg.weights, "scorer": "score_pair (rule-based, pre-v2)"},
    )
    return result


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="current", help="results file name, e.g. baseline")
    args = ap.parse_args()
    result = run(args.label)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.label}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    m = result["metrics"]
    print(f"SYNTHETIC dataset: {result['queries']} lost queries x {result['found_reports']} found reports, "
          f"{result['true_pairs']} true pairs, {result['hard_negative_pairs']} hard negatives")
    print(f"  precision@1                          {_pct(m['precision_at_1'])}")
    print(f"  recall@threshold ({result['config']['threshold']})         {_pct(m['recall_at_threshold'])}")
    print(f"  recall (retrieved, any score)        {_pct(m['recall_retrieved'])}")
    print(f"  false-positive rate (all negatives)  {_pct(m['false_positive_rate_all_negatives'])}")
    print(f"  false-positive rate (hard negatives) {_pct(m['false_positive_rate_hard_negatives'])}")
    print(f"  precision of notifications           {_pct(m['precision_of_notifications'])}")
    print(f"  notifications per query              {m['notifications_per_query']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
