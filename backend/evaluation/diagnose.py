"""Per-candidate diagnostics and offline policy counterfactuals on the SYNTHETIC evaluation sets.

For every (lost query, found report) candidate, this records the score, the lead the scorer assigned, the identity
and corroborating groups, and the typed-feature matches that produced them. The counterfactual rules below are
applied to the same stored candidates. Each rule is a notification policy, so the scorer itself is not changed.
The score does not depend on the identity rules, so a rule can be replayed exactly from the stored rows.

Metrics describe synthetic datasets only. They are not measured accuracy on real lost-and-found reports.

    python -m evaluation.diagnose --dataset targeted --label diag-targeted --dump <scratch>/diag-targeted.json
"""

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.config import MatchingConfig, get_matching_config
from app.ai.orchestrator import score_candidates
from app.ai.understanding import understand
from app.db.session import Base
from evaluation.run_eval import DATASETS, RESULTS, load_dataset, populate

NOTIFY_CAP = 3
LOCATION_CLOSE = 0.5  # location signal at or above this: roughly within 250 m, or the same place


def feature_matches(lu, fu) -> list[dict]:
    """Typed-feature pairs that overlap, as scoring v2 and v3 compare them (same kind, Jaccard >= 0.5)."""
    out = []
    for a in lu.typed_features:
        for b in fu.typed_features:
            if a.kind != b.kind or not a.tokens or not b.tokens:
                continue
            jac = len(a.tokens & b.tokens) / len(a.tokens | b.tokens)
            if jac < 0.5:
                continue
            conflict = bool(a.colors and b.colors and not (a.colors & b.colors))
            out.append({"kind": a.kind, "specific": a.specific and b.specific, "lost": a.phrase, "found": b.phrase,
                        "jac": round(jac, 3), "colour_conflict": conflict})
    return out


def candidate_rows(data: dict, db: Session, cfg: MatchingConfig) -> list[dict]:
    by_ext, ext_of = populate(db, data)
    truth = {tuple(p) for p in data["true_pairs"]}
    found_row = {f["id"]: f for f in data["found"]}
    case_of = {r["id"]: r.get("case") for r in data["lost"]}
    rows = []
    for lrow in data["lost"]:
        lid = lrow["id"]
        for lost, found, res in score_candidates(db, by_ext[lid], cfg):
            fid = ext_of[found.id]
            f = found_row[fid]
            rows.append({
                "query": lid, "found": fid, "role": f["role"], "origin": f.get("origin"),
                "negative_type": f.get("negative_type"), "case": case_of[lid], "true": (lid, fid) in truth,
                "score": res.score, "lead": res.lead, "notify_recorded": res.notify_eligible,
                "groups": list(res.identity_groups), "corroborating": list(res.corroborating),
                "category": res.signals.get("category"), "location": res.signals.get("location"),
                "matches": feature_matches(understand(lost), understand(found)),
                "explanation": res.explanation,
            })
    return rows


# ---- counterfactual notification rules -------------------------------------------------------------------

def _specific_accessory(r):
    return any(m["kind"] in ("accessory", "other") and m["specific"] and not m["colour_conflict"]
               for m in r["matches"])


def _location_close(r):
    return r["location"] is not None and r["location"] >= LOCATION_CLOSE


def _v3_recorded(r, thr):
    return r["notify_recorded"]


def _specific_accessory_two_group(r, thr):
    """The v3 two-group rule, with a specific accessory counted as an identity group."""
    identity = list(r["groups"]) + (["specific accessory"] if _specific_accessory(r) else [])
    corr = [c for c in r["corroborating"] if c != "accessory features"]
    return bool(identity) and len(identity) + len(corr) >= 2 and r["score"] >= thr


def _marking_only(r):
    """Identity rests on a marking or damage match alone: no model, no description, no specific accessory."""
    kinds = {m["kind"] for m in r["matches"] if not m["colour_conflict"]}
    return bool(kinds) and kinds <= {"marking", "damage"} and not (set(r["groups"]) - {"features"})


def _restrict(allowed):
    """A subtractive counterfactual: v3 stays, except marking-only notifications must also pass `allowed`."""
    return lambda r, thr: r["notify_recorded"] and (not _marking_only(r) or allowed(r))


def _loc(r):
    return _location_close(r)


def _other_than_colour(r):
    return any(c != "colour" for c in r["corroborating"])


def _specific_marking(r):
    return any(m["specific"] and not m["colour_conflict"] and m["kind"] in ("marking", "damage") for m in r["matches"])


# Subtractive: v3 notifications that depend on a marking alone must also pass one extra condition.
RESTRICTIONS = {
    "marking-only needs location": _restrict(_loc),
    "marking-only needs brand or accessory (not colour alone)": _restrict(_other_than_colour),
    "marking-only needs a specific marking (digits, initials, customised)": _restrict(_specific_marking),
    "marking-only needs location and brand or accessory": _restrict(lambda r: _loc(r) and _other_than_colour(r)),
}
# Additive: a pair notifies if v3 notifies it or the extra rule does.
EXTRAS = {
    "specific accessory as identity (two-group rule)": _specific_accessory_two_group,
}
RULES = {"v3 (recorded)": _v3_recorded}
for _name, _rule in RESTRICTIONS.items():
    RULES[f"v3 restricted: {_name}"] = _rule
for _name, _extra in EXTRAS.items():
    RULES[f"v3 + {_name}"] = (lambda e: lambda r, thr: r["notify_recorded"] or e(r, thr))(_extra)


def replay(rows: list[dict], rule, thr: float) -> dict:
    """Notify with `rule`, capped per query by score, then count outcomes. Counts are exact replays."""
    per_query = defaultdict(list)
    for r in rows:
        if rule(r, thr):
            per_query[r["query"]].append(r)
    notified = []
    for rs in per_query.values():
        rs.sort(key=lambda r: r["score"], reverse=True)
        notified.extend(rs[:NOTIFY_CAP])
    true_n = [r for r in notified if r["true"]]
    fp = [r for r in notified if not r["true"]]
    same_query_hard = [r for r in fp if r["role"] == "hard_negative" and r["origin"] == r["query"]]
    true_ids = {id(r) for r in true_n}
    true_total = sum(1 for r in rows if r["true"])
    n_queries = len({r["query"] for r in rows})
    recall_by_case = Counter()
    total_by_case = Counter()
    for r in rows:
        if r["true"]:
            total_by_case[r["case"]] += 1
            if id(r) in true_ids:
                recall_by_case[r["case"]] += 1
    return {
        "notified": len(notified),
        "true_notified": len(true_n),
        "recall": round(len(true_n) / true_total, 3) if true_total else None,
        "precision": round(len(true_n) / len(notified), 3) if notified else None,
        "notified_per_query": round(len(notified) / n_queries, 3) if n_queries else None,
        "fp_same_query_hard": len(same_query_hard),
        "fp_cross_query": len(fp) - len(same_query_hard),
        "recall_by_case": {c: f"{recall_by_case[c]}/{total_by_case[c]}" for c in sorted(total_by_case)},
        "false_positives": [{"query": r["query"], "found": r["found"], "role": r["role"],
                             "negative_type": r["negative_type"], "score": r["score"], "groups": r["groups"],
                             "corroborating": r["corroborating"], "matches": r["matches"]} for r in fp],
    }


def run(dataset: str, scorer: str, dump: Path | None) -> dict:
    cfg = get_matching_config()
    cfg = MatchingConfig(**{**cfg.__dict__, "scorer": scorer})
    data = load_dataset(DATASETS[dataset])
    with tempfile.TemporaryDirectory(prefix="lostlink-diag-") as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'diag.db'}")
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                rows = candidate_rows(data, db, cfg)
        finally:
            engine.dispose()
    if dump is not None:
        dump.parent.mkdir(parents=True, exist_ok=True)
        dump.write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")
    thr = cfg.threshold
    out = {"dataset": dataset, "scorer": scorer, "threshold": thr, "cap": NOTIFY_CAP,
           "candidate_rows": len(rows), "true_pairs": sum(1 for r in rows if r["true"]), "rules": {}}
    for name, rule in RULES.items():
        out["rules"][name] = replay(rows, rule, thr)
    # Sanity check: the recorded v3 lead must replay exactly from the stored rows.
    recorded = sum(1 for r in rows if r["notify_recorded"])
    out["recorded_notifications_before_cap"] = recorded
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    ap.add_argument("--scorer", default="v3", choices=["v1", "v2", "v3"])
    ap.add_argument("--label", required=True, help="summary file name in results/ (summary only, no candidate dump)")
    ap.add_argument("--dump", type=Path, default=None, help="optional full candidate dump (not committed)")
    args = ap.parse_args()
    result = run(args.dataset, args.scorer, args.dump)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{args.label}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.dataset} scorer={args.scorer}: {result['candidate_rows']} candidates, "
          f"{result['true_pairs']} true pairs")
    for name, r in result["rules"].items():
        print(f"  {name:<46} notif {r['notified']:>3}  true {r['true_notified']:>2}  recall {r['recall']}  "
              f"precision {r['precision']}  FP same-query {r['fp_same_query_hard']}  cross-query {r['fp_cross_query']}")


if __name__ == "__main__":
    main()
