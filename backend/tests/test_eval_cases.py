"""The identity-case set: its control features must not match any case feature (same kind, Jaccard >= 0.5)."""

from app.ai.understanding import extract_typed_features
from evaluation.generate_cases import CASES, CONTROL_FEATURES


def _overlaps(a: str, b: str) -> bool:
    for x in extract_typed_features(a):
        for y in extract_typed_features(b):
            if x.kind != y.kind or not x.tokens or not y.tokens:
                continue
            if len(x.tokens & y.tokens) / len(x.tokens | y.tokens) >= 0.5:
                return True
    return False


def test_control_features_do_not_overlap_any_case_feature():
    case_features = [f for spec in CASES.values() for f in spec["features"]]
    for control in CONTROL_FEATURES:
        for feature in case_features:
            assert not _overlaps(control, feature), (control, feature)


def test_control_features_are_typed():
    # A control with no typed feature would test "no feature", not "a different feature".
    for control in CONTROL_FEATURES:
        assert extract_typed_features(control), control
