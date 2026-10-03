"""Tunable matching configuration.

Weights are relative; signals that cannot be computed for a pair (e.g. no images)
are left out and the remaining weights are renormalised. Override any weight with
an env var such as MATCH_WEIGHT_IMAGE=0.1.
"""

import os
from dataclasses import dataclass, field

from app.core.config import get_settings

DEFAULT_WEIGHTS: dict[str, float] = {
    "category": 0.15,
    "text": 0.20,
    "color": 0.12,
    "brand": 0.08,
    "features": 0.10,
    "image": 0.10,  # low by default: local heuristic, not semantic vision
    "location": 0.15,
    "time": 0.10,
}


@dataclass(frozen=True)
class MatchingConfig:
    weights: dict[str, float] = field(default_factory=dict)
    threshold: float = 0.55  # store + notify at or above this
    high_confidence: float = 0.75
    max_candidates: int = 10
    # Retrieval window: a found item can be reported a bit before the stated loss time
    # (times are approximate) and up to N days after.
    time_slack_hours: float = 12
    max_days_after_loss: int = 60
    max_distance_km: float = 30
    # Campus scale: score ~0.75 at 100 m, ~0.24 at 500 m (falls to ~37% at this distance)
    location_scale_km: float = 0.35
    same_area_score: float = 0.8  # floor when both points are in the same campus area (e.g. sports grounds)
    time_scale_hours: float = 24
    # Description similarity: "bm25" (lexical, IDF-weighted) or "hashing" (the earlier hashed-vector fallback)
    text_method: str = "bm25"
    # Scorer: "v2" (identity-based leads) or "v1" (the earlier weighted score, kept as a fallback)
    scorer: str = "v1"
    # Notification cap per report per run (Strong and Possible leads only)
    max_notifications: int = 3


def get_matching_config() -> MatchingConfig:
    weights = dict(DEFAULT_WEIGHTS)
    for name in weights:
        raw = os.environ.get(f"MATCH_WEIGHT_{name.upper()}")
        if raw:
            try:
                weights[name] = max(0.0, float(raw))
            except ValueError:
                pass
    method = os.environ.get("MATCH_TEXT_METHOD", "bm25").strip().lower()
    scorer = os.environ.get("MATCH_SCORER", "v1").strip().lower()
    return MatchingConfig(weights=weights, threshold=get_settings().match_threshold,
                          text_method=method if method in ("bm25", "hashing") else "bm25",
                          scorer=scorer if scorer in ("v1", "v2") else "v1")
