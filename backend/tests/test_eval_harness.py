"""Checks for the offline evaluation harness and its SYNTHETIC dataset."""

import json
from collections import Counter

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from evaluation.generate_dataset import OUT_FILE, build
from evaluation.run_eval import _fp_type, evaluate, load_dataset


def test_committed_dataset_is_reproducible_and_labelled_synthetic():
    committed = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build()))  # generator output matches the committed file
    assert committed["dataset"] == "SYNTHETIC"
    assert "Invented for offline evaluation" in committed["notice"]


def test_dataset_shape():
    data = load_dataset()
    assert data["counts"]["true_pairs"] >= 50
    assert len(data["true_pairs"]) == len(set(map(tuple, data["true_pairs"])))
    ids = [r["id"] for r in data["lost"] + data["found"]]
    assert len(ids) == len(set(ids))

    roles = Counter(f["role"] for f in data["found"])
    assert roles["true_match"] == len(data["true_pairs"])
    assert roles["hard_negative"] >= 4 * len(data["lost"])
    # every true pair links a lost query to a found report with the same item type
    by_id = {r["id"]: r for r in data["lost"] + data["found"]}
    for lost_id, found_id in data["true_pairs"]:
        assert by_id[lost_id]["item_type"] == by_id[found_id]["item_type"]


def test_false_positive_labels_are_relative_to_the_query():
    own = {"role": "hard_negative", "origin": "L001", "negative_type": "hn-brand"}
    other = {"role": "hard_negative", "origin": "L002", "negative_type": "hn-brand"}
    assert _fp_type(own, "L001") == "hard:hn-brand"
    assert _fp_type(other, "L001") == "other_query_hard_negative"
    assert _fp_type({"role": "true_match", "origin": "L002"}, "L001") == "other_query_true_match"
    assert _fp_type({"role": "easy_negative"}, "L001") == "unrelated"


def test_evaluation_runs_on_a_small_slice(tmp_path):
    full = load_dataset()
    keep_lost = {r["id"] for r in full["lost"][:4]}
    found = [f for f in full["found"] if f.get("origin") in keep_lost or f["role"] == "easy_negative"][:120]
    keep_found = {f["id"] for f in found}
    data = {
        **full,
        "lost": full["lost"][:4],
        "found": found,
        "true_pairs": [p for p in full["true_pairs"] if p[0] in keep_lost and p[1] in keep_found],
    }
    engine = create_engine(f"sqlite:///{tmp_path / 'slice.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = evaluate(data, db)
    engine.dispose()

    assert result["queries"] == 4
    for key, value in result["metrics"].items():
        assert value is None or 0.0 <= value <= 1.0 or key == "notifications_per_query", key
    assert result["counts"]["true_notified"] <= len(data["true_pairs"])
    assert all(e["explanation"] for e in result["false_positive_examples"])
