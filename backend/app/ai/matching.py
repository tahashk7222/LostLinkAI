"""Matching Agent: combine deterministic evidence signals into a score and a structured explanation.

The score is a fixed weighted relevance value computed by rules. It is not a probability and
not proof of ownership.

Evidence strength is a rule-based label for how much one signal narrows the candidate:
- STRONG: distinctive or rarely shared attributes (brand, same place, close time, category)
- MODERATE: attributes many items share (colour, general description, near spot)
- WEAK: coarse or heuristic signals (same campus, distant spot, visual heuristic)
Each evidence item states its direction: "supports" or "contradicts".
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.config import MatchingConfig
from app.ai.providers import cosine, get_image_embedder, get_text_embedder
from app.ai.providers.text import tokenize
from app.ai.understanding import Understanding
from app.geo.geofence import area_of, get_geofence


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
    evidence: list[dict] = field(default_factory=list)
    lead: str | None = None  # STRONG | POSSIBLE | WEAK | None (not a lead)

    @property
    def reasons(self) -> list[str]:
        return [e["text"] for e in self.evidence if e["direction"] == "supports"]

    @property
    def concerns(self) -> list[str]:
        return [e["text"] for e in self.evidence if e["direction"] == "contradicts"]

    @property
    def explanation(self) -> list[str]:
        return self.reasons + [f"Note: {c}" for c in self.concerns]


class _Evidence:
    """Collects evidence items. Texts are built from public fields only; private details never reach here."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def support(self, signal: str, text: str, strength: str, value=None) -> None:
        self.items.append({"signal": signal, "text": text, "direction": "supports",
                           "strength": strength, "value": value})

    def contradict(self, signal: str, text: str, strength: str, value=None) -> None:
        self.items.append({"signal": signal, "text": text, "direction": "contradicts",
                           "strength": strength, "value": value})


def score_pair(lost, found, lu: Understanding, fu: Understanding, cfg: MatchingConfig,
               text_sim: float | None = None) -> MatchResult:
    """Score one lost/found pair. `text_sim` is the description similarity in [0, 1] (BM25 by default)."""
    signals: dict[str, float] = {}
    ev = _Evidence()

    # Category
    if lu.category == fu.category:
        signals["category"] = 1.0
        ev.support("category", f"Same item category ({lu.category})", "STRONG", lu.category)
    elif lu.category_group == fu.category_group and lu.category_group != "other":
        signals["category"] = 0.5
        ev.support("category", f"Related item type ({lu.category} / {fu.category})", "WEAK")
    else:
        signals["category"] = 0.0
        ev.contradict("category", "Item categories differ", "STRONG")

    # Text (lexical similarity of public descriptions)
    if text_sim is None:
        text_sim = cosine(lost.text_embedding, found.text_embedding)
    signals["text"] = round(text_sim, 3)
    if signals["text"] >= 0.5:
        ev.support("text", "Descriptions are very similar", "STRONG", signals["text"])
    elif signals["text"] >= 0.3:
        ev.support("text", "Descriptions share several details", "MODERATE", signals["text"])

    # Colour (shared by many items, so moderate)
    if lu.colors and fu.colors:
        common = lu.colors & fu.colors
        signals["color"] = 1.0 if common else 0.0
        if common:
            ev.support("color", f"Compatible colour ({', '.join(sorted(common))})", "MODERATE", 1.0)
        else:
            ev.contradict("color", "Reported colours differ", "MODERATE")

    # Brand / model
    if lu.brand and fu.brand:
        same = lu.brand == fu.brand
        signals["brand"] = 1.0 if same else 0.0
        if same:
            ev.support("brand", f"Same brand ({lu.brand.title()})", "STRONG", lu.brand)
        else:
            ev.contradict("brand", "Reported brands differ", "STRONG")
        if same and lost.model and found.model and _jaccard(lost.model, found.model) >= 0.5:
            ev.support("model", "Same or similar model", "STRONG")

    # Distinctive features
    lf = " ".join(lu.features) or (lost.distinctive_features or "")
    ff = " ".join(fu.features) or (found.distinctive_features or "")
    if lf.strip() and ff.strip():
        embed = get_text_embedder().embed
        signals["features"] = round(cosine(embed(lf), embed(ff)), 3)
        if signals["features"] >= 0.35:
            ev.support("features", "Similar distinctive feature described", "MODERATE", signals["features"])

    # Image (colour and shape heuristic, not object recognition)
    lost_imgs = [i.embedding for i in lost.images if i.embedding]
    found_imgs = [i.embedding for i in found.images if i.embedding]
    if lost_imgs and found_imgs:
        img = get_image_embedder()
        best = max(img.similarity(a, b) for a in lost_imgs for b in found_imgs)
        signals["image"] = round(best, 3)
        if best >= 0.7:
            ev.support("image", "Photos look visually similar (colour and shape)", "MODERATE", signals["image"])
        elif best >= 0.55:
            ev.support("image", "Photos are somewhat visually similar", "WEAK", signals["image"])

    # Location: campus-scale distance, plus same place / same campus area / zone
    if None not in (lost.latitude, lost.longitude, found.latitude, found.longitude):
        km = haversine_km(lost.latitude, lost.longitude, found.latitude, found.longitude)
        loc = math.exp(-km / cfg.location_scale_km)
        lost_place, found_place = getattr(lost, "place_key", None), getattr(found, "place_key", None)
        lost_area = area_of(lost.latitude, lost.longitude, lost_place)
        if lost_place and lost_place == found_place:
            loc = 1.0
            place = get_geofence().place(lost_place)
            ev.support("location", f"Both reported at {place.name if place else found.location}", "STRONG", 1.0)
        else:
            if lost_area and lost_area == area_of(found.latitude, found.longitude, found_place):
                loc = max(loc, cfg.same_area_score)
            if km < 0.03:
                ev.support("location", "Found at practically the same spot", "STRONG", round(km, 3))
            elif km < 1:
                ev.support("location", f"Found about {round(km * 1000, -1):.0f} m from where it was lost",
                           "STRONG" if km < 0.15 else "MODERATE", round(km, 3))
            else:
                ev.support("location", f"Found about {km:.1f} km from the reported loss location", "WEAK",
                           round(km, 3))
        if getattr(lost, "zone", None) == getattr(found, "zone", None) == "campus":
            ev.support("zone", "Both on UET Lahore campus", "WEAK")
        signals["location"] = round(loc, 3)
    else:
        sim = _jaccard(lost.location, found.location)
        signals["location"] = round(min(1.0, sim * 1.5), 3)
        if sim >= 0.3:
            ev.support("location", f"Similar location described ('{found.location}')", "MODERATE", round(sim, 3))

    # Time: found should be at/after loss (allowing slack for approximate times)
    delta_h = (as_utc(found.date_time) - as_utc(lost.date_time)).total_seconds() / 3600
    if delta_h < -cfg.time_slack_hours:
        signals["time"] = 0.0
        ev.contradict("time", "Item was reported found before it was reported lost", "STRONG", round(delta_h, 1))
    else:
        signals["time"] = round(math.exp(-max(0.0, delta_h) / cfg.time_scale_hours), 3)
        if delta_h >= 0:
            ev.support("time", f"Found approximately {_fmt_hours(delta_h)} after the reported loss",
                       "MODERATE" if delta_h <= 6 else "WEAK", round(delta_h, 1))
        else:
            ev.support("time", "Reported times overlap (approximate)", "WEAK", round(delta_h, 1))

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
    lead = "POSSIBLE" if score >= cfg.threshold else None  # v1: a single weighted score, no identity rules
    return MatchResult(score, confidence, signals, ev.items, lead)
