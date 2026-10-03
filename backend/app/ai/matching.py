"""Matching Agent: combine evidence signals into a score and an explanation.

The score expresses *relevance of a candidate*, not proof of ownership.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.config import MatchingConfig
from app.ai.providers import cosine, get_image_embedder, get_text_embedder
from app.ai.providers.text import tokenize
from app.ai.understanding import Understanding


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _jaccard(a: str | None, b: str | None) -> float:
    ta, tb = set(tokenize(a or "")), set(tokenize(b or ""))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _fmt_hours(h: float) -> str:
    if h < 1:
        return f"{max(1, round(h * 60))} minutes"
    if h < 48:
        return f"{h:.1f} hours".replace(".0 ", " ")
    return f"{round(h / 24)} days"


@dataclass
class MatchResult:
    score: float
    confidence: str
    signals: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)

    @property
    def explanation(self) -> list[str]:
        return self.reasons + [f"Note: {c}" for c in self.concerns]


def score_pair(lost, found, lu: Understanding, fu: Understanding, cfg: MatchingConfig) -> MatchResult:
    signals: dict[str, float] = {}
    reasons: list[str] = []
    concerns: list[str] = []

    # Category
    if lu.category == fu.category:
        signals["category"] = 1.0
        reasons.append(f"Same item category ({lu.category})")
    elif lu.category_group == fu.category_group and lu.category_group != "other":
        signals["category"] = 0.5
        reasons.append(f"Related item type ({lu.category} / {fu.category})")
    else:
        signals["category"] = 0.0
        concerns.append("Item categories differ")

    # Text (semantic-lexical similarity of public descriptions)
    signals["text"] = round(cosine(lost.text_embedding, found.text_embedding), 3)
    if signals["text"] >= 0.5:
        reasons.append("Descriptions are very similar")
    elif signals["text"] >= 0.3:
        reasons.append("Descriptions share several details")

    # Colour
    if lu.colors and fu.colors:
        common = lu.colors & fu.colors
        signals["color"] = 1.0 if common else 0.0
        if common:
            reasons.append(f"Compatible colour ({', '.join(sorted(common))})")
        else:
            concerns.append("Reported colours differ")

    # Brand / model
    if lu.brand and fu.brand:
        same = lu.brand == fu.brand
        signals["brand"] = 1.0 if same else 0.0
        if same:
            reasons.append(f"Same brand ({lu.brand.title()})")
        else:
            concerns.append("Reported brands differ")
        if same and lost.model and found.model and _jaccard(lost.model, found.model) >= 0.5:
            reasons.append("Same or similar model")

    # Distinctive features
    lf = " ".join(lu.features) or (lost.distinctive_features or "")
    ff = " ".join(fu.features) or (found.distinctive_features or "")
    if lf.strip() and ff.strip():
        embed = get_text_embedder().embed
        signals["features"] = round(cosine(embed(lf), embed(ff)), 3)
        if signals["features"] >= 0.35:
            reasons.append("Similar distinctive feature described")

    # Image (heuristic visual features)
    lost_imgs = [i.embedding for i in lost.images if i.embedding]
    found_imgs = [i.embedding for i in found.images if i.embedding]
    if lost_imgs and found_imgs:
        img = get_image_embedder()
        best = max(img.similarity(a, b) for a in lost_imgs for b in found_imgs)
        signals["image"] = round(best, 3)
        if best >= 0.7:
            reasons.append("Photos look visually similar (colour and shape)")
        elif best >= 0.55:
            reasons.append("Photos are somewhat visually similar")

    # Location
    if None not in (lost.latitude, lost.longitude, found.latitude, found.longitude):
        km = haversine_km(lost.latitude, lost.longitude, found.latitude, found.longitude)
        signals["location"] = round(math.exp(-km / cfg.location_scale_km), 3)
        reasons.append(f"Found about {km:.1f} km from the reported loss location" if km >= 0.1
                       else "Found at practically the same location")
    else:
        sim = _jaccard(lost.location, found.location)
        signals["location"] = round(min(1.0, sim * 1.5), 3)
        if sim >= 0.3:
            reasons.append(f"Similar location described ('{found.location}')")

    # Time: found should be at/after loss (allowing slack for approximate times)
    delta_h = (as_utc(found.date_time) - as_utc(lost.date_time)).total_seconds() / 3600
    if delta_h < -cfg.time_slack_hours:
        signals["time"] = 0.0
        concerns.append("Item was reported found before it was reported lost")
    else:
        signals["time"] = round(math.exp(-max(0.0, delta_h) / cfg.time_scale_hours), 3)
        if delta_h >= 0:
            reasons.append(f"Found approximately {_fmt_hours(delta_h)} after the reported loss")
        else:
            reasons.append("Reported times overlap (approximate)")

    usable = {k: v for k, v in signals.items() if cfg.weights.get(k, 0) > 0}
    total_w = sum(cfg.weights[k] for k in usable)
    score = sum(cfg.weights[k] * v for k, v in usable.items()) / total_w if total_w else 0.0

    # Hard contradictions cap the score: different category or brand makes a match unlikely.
    if signals.get("category") == 0.0:
        score = min(score, 0.4)
    if signals.get("brand") == 0.0:
        score *= 0.8

    score = round(max(0.0, min(1.0, score)), 3)
    confidence = "HIGH" if score >= cfg.high_confidence else "MEDIUM" if score >= cfg.threshold else "LOW"
    return MatchResult(score, confidence, signals, reasons, concerns)
