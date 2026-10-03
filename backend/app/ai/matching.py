"""Matching: deterministic signals, a relevance score, and a lead label per candidate pair.

Nothing here is a learned model. Every value comes from fixed rules, so the same inputs always give
the same result. The score is a relevance value on [0, 1]. It is not a probability, and it is not
evidence of ownership.

Signals fall into two groups:
- Identity signals say the item itself matches: description, distinctive features, brand/model,
  colour, and (corroboration only) visual similarity.
- Context signals say where and when: location and time. Category is a gate with its own weight.
  It is not identity.

Scoring v2 (default) notifies only on identity evidence:
- A lead qualifies only when a distinctive identity signal (brand/model or a typed feature) and at
  least one other identity signal both hold. Category, location and time alone never qualify, and a
  visually similar photo alone never qualifies.
- Missing identity evidence lowers the score through a coverage factor, so absence never inflates it.
- Contradictions cap the score: category, brand, model, colour, feature or time conflicts.
- Labels: STRONG (score >= strong_score, qualifies, at least three supporting identity signals, no strong
  contradiction), POSSIBLE (score >= threshold, qualifies), WEAK (identity support, score >= weak_score,
  stored but not notified), or None (not a lead).

Scoring v1 is the earlier weighted average, kept as a fallback (MATCH_SCORER=v1).

Evidence strength is a rule label for how much one item narrows the candidate: STRONG, MODERATE or WEAK.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.config import MatchingConfig
from app.ai.providers import cosine, get_image_embedder
from app.ai.providers.text import tokenize
from app.ai.understanding import Understanding, color_compatibility
from app.geo.geofence import area_of, get_geofence

# Scoring v2 weights. Identity signals are IDENTITY_V2; context and category make up the rest.
W_V2 = {"category": 0.14, "text": 0.22, "features": 0.14, "brand": 0.14, "color": 0.08, "image": 0.08,
        "location": 0.12, "time": 0.08}
IDENTITY_V2 = ("text", "features", "brand", "color", "image")
IDENTITY_TOTAL = sum(W_V2[k] for k in IDENTITY_V2)

DESCRIPTION_IDENTITY = 0.35  # description similarity needed to count as an identity group
FEATURE_IDENTITY = 0.5  # typed-feature overlap needed to count as an identity group
VISUAL_CORROBORATION = 0.7  # visual similarity that corroborates identity (never creates it)


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
        value = f"{h:.1f}".rstrip("0").rstrip(".")
        return f"{value} hour" if value == "1" else f"{value} hours"
    return f"{round(h / 24)} days"


@dataclass
class MatchResult:
    score: float
    confidence: str
    signals: dict[str, float]
    evidence: list[dict] = field(default_factory=list)
    lead: str | None = None  # STRONG | POSSIBLE | WEAK | None (not a lead)
    identity_groups: list[str] = field(default_factory=list)
    caps: dict[str, float] = field(default_factory=dict)  # contradiction caps that applied
    coverage: float | None = None  # share of identity weight that could be compared (v2)

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


_NO_TEXT_SIGNAL = object()  # callers that omit text_sim get the hashed-vector similarity (fallback path)


def _feature_signal(lf, ff, ev: _Evidence, caps: dict[str, float]) -> float | None:
    """Compare typed distinctive features. Only features of the same type are compared.

    None when either side has no typed features (absent, not contrary). 0 with a contradiction when both
    have features and none overlap. A same-type pair that overlaps but has conflicting colours (a red and
    a blue keychain) is a contradiction that caps the score.
    """
    if not lf or not ff:
        return None
    best, best_pair, conflict = 0.0, None, None
    for a in lf:
        for b in ff:
            if a.kind != b.kind or not a.tokens or not b.tokens:
                continue
            jac = len(a.tokens & b.tokens) / len(a.tokens | b.tokens)
            if jac < FEATURE_IDENTITY:
                continue
            if a.colors and b.colors and not (a.colors & b.colors):
                conflict = conflict or (a, b)
            elif jac > best:
                best, best_pair = jac, (a, b)
    if best_pair:
        a, _ = best_pair
        strength = "STRONG" if best >= 0.75 and a.kind != "other" else "MODERATE"
        ev.support("features", f"Similar {a.kind} described: '{a.phrase}'", strength, round(best, 3))
        return round(best, 3)
    if conflict:
        a, b = conflict
        ev.contradict("features", f"Different {a.kind} colour ('{a.phrase}' vs '{b.phrase}')", "STRONG")
        caps["features"] = 0.6
        return 0.0
    ev.contradict("features", "Distinctive features differ", "MODERATE")
    caps["features"] = 0.7
    return 0.0


def score_pair(lost, found, lu: Understanding, fu: Understanding, cfg: MatchingConfig,
               text_sim=_NO_TEXT_SIGNAL) -> MatchResult:
    """Score one lost/found pair.

    `text_sim` is the description similarity in [0, 1], or None when it cannot be computed (the signal is
    then absent, not zero). Omitting it uses the hashed-vector similarity.
    """
    signals: dict[str, float] = {}
    ev = _Evidence()
    caps: dict[str, float] = {}

    # Category (a gate, not identity)
    if lu.category == fu.category:
        signals["category"] = 1.0
        ev.support("category", f"Same item category ({lu.category})", "STRONG", lu.category)
    elif lu.category_group == fu.category_group and lu.category_group != "other":
        signals["category"] = 0.5
        ev.support("category", f"Related item type ({lu.category} / {fu.category})", "WEAK")
    else:
        signals["category"] = 0.0
        ev.contradict("category", "Item categories differ", "STRONG")
        caps["category"] = 0.35

    # Description (identity). Absent when either description has no identity terms.
    if text_sim is _NO_TEXT_SIGNAL:
        text_sim = cosine(lost.text_embedding, found.text_embedding)
    if text_sim is not None:
        signals["text"] = round(text_sim, 3)
        if signals["text"] >= 0.5:
            ev.support("text", "Descriptions are very similar", "STRONG", signals["text"])
        elif signals["text"] >= 0.3:
            ev.support("text", "Descriptions share several details", "MODERATE", signals["text"])

    # Colour (identity when the families match; a near match is partial; a conflict is a contradiction)
    compat = color_compatibility(lu.colors, fu.colors)
    if compat:
        kind, value = compat
        signals["color"] = value
        if kind == "same":
            ev.support("color", f"Compatible colour ({', '.join(sorted(lu.colors & fu.colors))})", "MODERATE", 1.0)
        elif kind == "near":
            ev.support("color", f"Similar colour ({', '.join(sorted(lu.colors))} / {', '.join(sorted(fu.colors))})",
                       "WEAK", 0.5)
        else:
            ev.contradict("color", "Reported colours differ", "MODERATE")
            caps["color"] = 0.6

    # Brand and model (identity). A model conflict is a brand/model contradiction.
    brand_sig = None
    if lu.brand and fu.brand:
        same = lu.brand == fu.brand
        brand_sig = 1.0 if same else 0.0
        if same:
            ev.support("brand", f"Same brand ({lu.brand.title()})", "STRONG", lu.brand)
        else:
            ev.contradict("brand", "Reported brands differ", "STRONG")
            caps["brand"] = 0.45
    shared_models = set(lu.models) & set(fu.models)
    if shared_models:
        if brand_sig in (None, 1.0):
            brand_sig = 1.0
        ev.support("model", f"Same or similar model ({sorted(shared_models)[0]})", "STRONG")
    elif lu.models and fu.models:
        brand_sig = 0.0
        ev.contradict("model", "Reported models differ", "STRONG")
        caps["model"] = 0.5
    if brand_sig is not None:
        signals["brand"] = brand_sig

    # Typed distinctive features (identity)
    feat = _feature_signal(lu.typed_features, fu.typed_features, ev, caps)
    if feat is not None:
        signals["features"] = feat

    # Image (visual heuristic, not object recognition). Corroboration only.
    lost_imgs = [i.embedding for i in lost.images if i.embedding]
    found_imgs = [i.embedding for i in found.images if i.embedding]
    if lost_imgs and found_imgs:
        img = get_image_embedder()
        best = max(img.similarity(a, b) for a in lost_imgs for b in found_imgs)
        signals["image"] = round(best, 3)
        if best >= VISUAL_CORROBORATION:
            ev.support("image", "Photos look visually similar (colour and shape)", "MODERATE", signals["image"])
        elif best >= 0.55:
            ev.support("image", "Photos are somewhat visually similar", "WEAK", signals["image"])

    # Location (context): campus-scale distance, plus same place / same campus area / zone
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

    # Time (context): found should be at/after loss (allowing slack for approximate times)
    delta_h = (as_utc(found.date_time) - as_utc(lost.date_time)).total_seconds() / 3600
    if delta_h < -cfg.time_slack_hours:
        signals["time"] = 0.0
        ev.contradict("time", "Item was reported found before it was reported lost", "STRONG", round(delta_h, 1))
        caps["time"] = 0.3
    else:
        signals["time"] = round(math.exp(-max(0.0, delta_h) / cfg.time_scale_hours), 3)
        if delta_h >= 0:
            ev.support("time", f"Found approximately {_fmt_hours(delta_h)} after the reported loss",
                       "MODERATE" if delta_h <= 6 else "WEAK", round(delta_h, 1))
        else:
            ev.support("time", "Reported times overlap (approximate)", "WEAK", round(delta_h, 1))

    if cfg.scorer == "v1":
        return _combine_v1(signals, ev, cfg)
    return _combine_v2(signals, ev, caps, cfg)


def _identity_groups(signals: dict[str, float]) -> list[str]:
    """Non-visual identity groups that hold for this pair."""
    groups = []
    if signals.get("text", 0.0) >= DESCRIPTION_IDENTITY:
        groups.append("description")
    if signals.get("features", 0.0) >= FEATURE_IDENTITY:
        groups.append("features")
    if signals.get("brand") == 1.0:
        groups.append("brand_model")
    if signals.get("color") == 1.0:
        groups.append("colour")
    return groups


def _combine_v2(signals: dict[str, float], ev: _Evidence, caps: dict[str, float], cfg: MatchingConfig) -> MatchResult:
    weights = {k: W_V2[k] for k in signals}
    mean = sum(weights[k] * signals[k] for k in signals) / sum(weights.values())
    coverage = sum(W_V2[k] for k in IDENTITY_V2 if k in signals) / IDENTITY_TOTAL
    score = mean * (0.5 + 0.5 * coverage)  # missing identity evidence lowers the score
    if caps:
        score = min(score, min(caps.values()))
    score = round(max(0.0, min(1.0, score)), 3)

    groups = _identity_groups(signals)
    visual = signals.get("image", 0.0) >= VISUAL_CORROBORATION and bool(groups)
    # Qualifying combinations. Brand plus colour is common on campus (many black JanSport bags), so it is
    # not identity on its own: brand needs a description match, and colour alone never qualifies.
    qualifies = len(groups) >= 2 and ("features" in groups or ("brand_model" in groups and "description" in groups))
    supports = len(groups) + (1 if visual else 0)
    strong_contradiction = any(e["direction"] == "contradicts" and e["strength"] == "STRONG" for e in ev.items)

    if qualifies and score >= cfg.strong_score and supports >= 3 and not strong_contradiction:
        lead = "STRONG"
    elif qualifies and score >= cfg.threshold:
        lead = "POSSIBLE"
    elif groups and score >= cfg.weak_score:
        lead = "WEAK"
    else:
        lead = None
    confidence = "HIGH" if lead == "STRONG" else "MEDIUM" if lead == "POSSIBLE" else "LOW"
    return MatchResult(score, confidence, signals, ev.items, lead, groups, caps, round(coverage, 3))


def _combine_v1(signals: dict[str, float], ev: _Evidence, cfg: MatchingConfig) -> MatchResult:
    """The earlier weighted average with its original caps. Kept as a fallback."""
    usable = {k: v for k, v in signals.items() if cfg.weights.get(k, 0) > 0}
    total_w = sum(cfg.weights[k] for k in usable)
    score = sum(cfg.weights[k] * v for k, v in usable.items()) / total_w if total_w else 0.0
    if signals.get("category") == 0.0:
        score = min(score, 0.4)
    if signals.get("brand") == 0.0:
        score *= 0.8
    score = round(max(0.0, min(1.0, score)), 3)
    confidence = "HIGH" if score >= cfg.high_confidence else "MEDIUM" if score >= cfg.threshold else "LOW"
    lead = "POSSIBLE" if score >= cfg.threshold else None
    return MatchResult(score, confidence, signals, ev.items, lead, _identity_groups(signals))
