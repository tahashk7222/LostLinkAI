"""Matching: deterministic signals, a relevance score, and a lead label per candidate pair.

Nothing here is a learned model. Every value comes from fixed rules, so the same inputs always give
the same result. The score is a relevance value on [0, 1]. It is not a probability, and it is not
evidence of ownership.

Signals fall into two groups:
- Identity signals say the item itself matches: description, distinctive features, brand/model,
  colour, and (corroboration only) visual similarity.
- Context signals say where and when: location and time. Category is a gate with its own weight.
  It is not identity.

Three concepts are kept apart on every result:
- relevance (`score`): a ranking value from the weighted signals. It is not a probability.
- lead label (`lead`): STRONG, POSSIBLE, WEAK or None, from the identity rules below.
- notification eligibility (`notify_eligible`): true only for STRONG and POSSIBLE leads.

Scoring v3 (default). Attributes are split by how much they identify an item:
- Identity-bearing groups can qualify a lead: a shared model code, a matching typed feature of kind
  marking (engraving, name, initials, number) or damage (scratch, dent, crack), and a description
  match after removing accessory wording and the shared generic words (see `pair_similarity`).
- Corroborating (generic) attributes never qualify a lead on their own: brand, colour, and accessory
  features (keychain, tag, strap, sticker). A common brand is found on many items, so brand is not
  identity without another identity-bearing group.
- A lead qualifies when at least one identity-bearing group and at least two groups in total hold.
  Category, location, time and a visually similar photo never qualify a lead, and never notify.
- Missing identity evidence lowers the score through a coverage factor, so absence never inflates it.
- Contradictions cap the score: category, brand, model, colour, feature or time conflicts.
- Labels: STRONG (score >= strong_score, qualifies, at least three groups in total, no strong
  contradiction), POSSIBLE (score >= threshold, qualifies), WEAK (any identity or corroborating match,
  score >= weak_score: stored, shown, never notified and never verifiable), or None (not a lead).

Scoring v2 is the earlier rule, kept reproducible (MATCH_SCORER=v2). It treated brand plus a description
match as identity and counted accessory features as identity, which let a common brand on a key ring
notify.

Scoring v1 is the earlier weighted average, kept as a fallback (MATCH_SCORER=v1).

Evidence strength is a rule label for how much one item narrows the candidate: STRONG, MODERATE or WEAK.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.ai.config import MatchingConfig
from app.ai.providers import cosine
from app.ai.visual import visual_evidence
from app.ai.providers.text import tokenize
from app.ai.understanding import Understanding, color_compatibility
from app.geo.geofence import NEAR_M, area_of, distance_m, get_geofence

# Scoring v2 weights. Identity signals are IDENTITY_V2; context and category make up the rest.
W_V2 = {"category": 0.14, "text": 0.22, "features": 0.14, "brand": 0.14, "color": 0.08, "image": 0.08,
        "location": 0.12, "time": 0.08}
IDENTITY_V2 = ("text", "features", "brand", "color", "image")
IDENTITY_TOTAL = sum(W_V2[k] for k in IDENTITY_V2)

DESCRIPTION_IDENTITY = 0.35  # description similarity needed to count as an identity group
FEATURE_IDENTITY = 0.5  # typed-feature overlap needed to count as an identity group
VISUAL_CORROBORATION = 0.7  # visual similarity that corroborates identity (never creates it)

# Typed-feature kinds that identify one item (v3). Accessory and other features are generic: many items
# carry a keychain or a sticker, so they corroborate but never qualify a lead on their own.
IDENTITY_FEATURE_KINDS = frozenset({"marking", "damage"})


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
    identity_groups: list[str] = field(default_factory=list)  # groups that can qualify a lead (v2, v3)
    corroborating: list[str] = field(default_factory=list)  # generic groups that support but never qualify (v3)
    caps: dict[str, float] = field(default_factory=dict)  # contradiction caps that applied
    coverage: float | None = None  # share of identity weight that could be compared (v2, v3)
    notify_eligible: bool = False  # the notification policy: only STRONG and POSSIBLE leads notify

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


IDENTIFIER_CONFLICT_CAP = 0.45  # a conflicting identifier (serial, initials, name) keeps the pair below threshold


def _feature_signal(lf, ff, ev: _Evidence, caps: dict[str, float], identifiers: bool = False
                    ) -> tuple[float | None, frozenset[str], bool]:
    """Compare typed distinctive features. Only features of the same type are compared.

    Returns (similarity, kinds). The similarity is None when either side has no typed features (absent,
    not contrary); it is 0 with a contradiction when both have features and none overlap. `kinds` holds
    the feature kinds that overlap without a colour conflict. A same-type pair that overlaps but has
    conflicting colours (a red and a blue keychain) is a contradiction that caps the score.
    """
    if not lf or not ff:
        return None, frozenset(), False
    best, best_pair, conflict, id_conflict, id_match = 0.0, None, None, None, False
    matched: set[str] = set()
    for a in lf:
        for b in ff:
            if a.kind != b.kind or not a.tokens or not b.tokens:
                continue
            jac = len(a.tokens & b.tokens) / len(a.tokens | b.tokens)
            identical = False
            if identifiers and a.identifiers and b.identifiers:
                only_a, only_b = a.identifiers - b.identifiers, b.identifiers - a.identifiers
                if only_a and only_b:
                    # Each side states an identifier the other does not (serial 4821 vs 9075, initials AK vs MR).
                    # Such a pair is never a match, whatever the word overlap. A side that states fewer identifiers
                    # is not a contradiction.
                    id_conflict = id_conflict or (a, b)
                    continue
                if not only_a and not only_b:
                    jac = max(jac, FEATURE_IDENTITY)  # identical identifiers match, whatever the wording
                    identical = True
            if jac < FEATURE_IDENTITY:
                continue
            if a.colors and b.colors and not (a.colors & b.colors):
                conflict = conflict or (a, b)
            else:
                matched.add(a.kind)
                id_match = id_match or identical
                if jac > best:
                    best, best_pair = jac, (a, b)
    if id_conflict:
        a, b = id_conflict
        ev.contradict("features", f"Different identifiers ('{a.phrase}' vs '{b.phrase}')", "STRONG")
        caps["features"] = IDENTIFIER_CONFLICT_CAP
    if best_pair:
        a, _ = best_pair
        strength = "STRONG" if best >= 0.75 and a.kind != "other" else "MODERATE"
        ev.support("features", f"Similar {a.kind} described: '{a.phrase}'", strength, round(best, 3))
        return round(best, 3), frozenset(matched), id_match
    if id_conflict:
        return 0.0, frozenset(), False
    if conflict:
        a, b = conflict
        ev.contradict("features", f"Different {a.kind} colour ('{a.phrase}' vs '{b.phrase}')", "STRONG")
        caps["features"] = 0.6
        return 0.0, frozenset(), False
    ev.contradict("features", "Distinctive features differ", "MODERATE")
    caps["features"] = 0.7
    return 0.0, frozenset(), False


def generic_identity_terms(report, u: Understanding) -> frozenset[str]:
    """Words that are not identity for the description signal (scoring v3).

    Removed from the description before it counts as identity: the report's own brand, colour, category and
    model fields (a brand word in a description is brand evidence, whether or not the vocabulary knows the
    brand), and the words of accessory and other features (many items share a keychain or a sticker)."""
    terms: set[str] = set()
    for value in (getattr(report, "brand", None), getattr(report, "color", None),
                  getattr(report, "category", None), getattr(report, "model", None)):
        if value:
            terms |= set(tokenize(str(value)))
    for f in u.typed_features:
        if f.kind not in IDENTITY_FEATURE_KINDS:
            terms |= f.tokens
    return frozenset(terms)


def score_pair(lost, found, lu: Understanding, fu: Understanding, cfg: MatchingConfig,
               text_sim=_NO_TEXT_SIGNAL, identity_sim: float | None = None) -> MatchResult:
    """Score one lost/found pair.

    `text_sim` is the description similarity in [0, 1], or None when it cannot be computed (the signal is
    then absent, not zero). Omitting it uses the hashed-vector similarity.
    `identity_sim` is the description similarity without generic wording (scoring v3 identity). None means
    no identity words were compared.
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
    feat, feat_kinds, feat_id_match = _feature_signal(lu.typed_features, fu.typed_features, ev, caps,
                                                      identifiers=cfg.scorer == "v3")
    if feat is not None:
        signals["features"] = feat

    # Image: structured visual evidence (learned model or heuristic, see app/ai/visual.py). Corroboration only.
    vis = visual_evidence(lost.images, found.images)
    if vis["available"]:
        best = vis["similarity"]
        signals["image"] = best
        how = "a learned visual model" if vis["method"] == "learned" else "colour and shape"
        if best >= VISUAL_CORROBORATION:
            ev.support("image", f"Photos look visually similar ({how})", "MODERATE", best)
        elif best >= 0.55:
            ev.support("image", f"Photos are somewhat visually similar ({how})", "WEAK", best)

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
    if cfg.scorer == "v2":
        return _combine_v2(signals, ev, caps, cfg)
    return _combine_v3(signals, ev, caps, cfg, feat_kinds=feat_kinds, model_shared=bool(shared_models),
                       identity_sim=identity_sim, colour_conflict="color" in caps,
                       strong_identity=bool(shared_models) or feat_id_match, close=_is_close(lost, found))


def _is_close(lost, found) -> bool:
    """Same place, or within the existing 250 m "near" distance. Missing coordinates are not close."""
    lp, fp = getattr(lost, "place_key", None), getattr(found, "place_key", None)
    if lp and lp == fp:
        return True
    pts = [(getattr(r, "latitude", None), getattr(r, "longitude", None)) for r in (lost, found)]
    if any(v is None for pt in pts for v in pt):
        return False
    return distance_m(*pts[0], *pts[1]) <= NEAR_M


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
    return MatchResult(score=score, confidence=confidence, signals=signals, evidence=ev.items, lead=lead,
                       identity_groups=groups, caps=caps, coverage=round(coverage, 3),
                       notify_eligible=lead in NOTIFY_LEADS)


NOTIFY_LEADS = ("STRONG", "POSSIBLE")


def _combine_v3(signals: dict[str, float], ev: _Evidence, caps: dict[str, float], cfg: MatchingConfig, *,
                feat_kinds: frozenset[str], model_shared: bool, identity_sim: float | None,
                colour_conflict: bool = False, strong_identity: bool = False, close: bool = True) -> MatchResult:
    """Scoring v3: identity-bearing groups qualify a lead; generic attributes only corroborate.

    The relevance score is the same weighted mean as v2 (with the coverage factor and caps). The lead
    label and notification eligibility come from the identity groups below, not from the score alone.
    """
    weights = {k: W_V2[k] for k in signals}
    mean = sum(weights[k] * signals[k] for k in signals) / sum(weights.values())
    coverage = sum(W_V2[k] for k in IDENTITY_V2 if k in signals) / IDENTITY_TOTAL
    score = mean * (0.5 + 0.5 * coverage)
    if caps:
        score = min(score, min(caps.values()))
    score = round(max(0.0, min(1.0, score)), 3)

    identity, corroborating = _v3_groups(signals, feat_kinds, model_shared, identity_sim)
    # Marking or damage alone, with the two reports not close: the relevance score stays, but this identity does not
    # qualify for notification. The lead is at most Weak.
    qualifying = [] if identity == ["features"] and not close else identity
    visual = signals.get("image", 0.0) >= VISUAL_CORROBORATION and bool(identity)  # corroborates, never creates
    total = len(identity) + len(corroborating) + (1 if visual else 0)
    qualifies = bool(qualifying) and len(qualifying) + len(corroborating) >= 2
    # A reported colour conflict blocks notification unless a strong identity (model code or matched identifier) exists.
    if colour_conflict and not strong_identity:
        qualifies = False
    strong_contradiction = any(e["direction"] == "contradicts" and e["strength"] == "STRONG" for e in ev.items)

    if qualifies and score >= cfg.strong_score and total >= 3 and not strong_contradiction:
        lead = "STRONG"
    elif qualifies and score >= cfg.threshold:
        lead = "POSSIBLE"
    elif (identity or corroborating) and score >= cfg.weak_score:
        lead = "WEAK"
    else:
        lead = None
    confidence = "HIGH" if lead == "STRONG" else "MEDIUM" if lead == "POSSIBLE" else "LOW"
    return MatchResult(score=score, confidence=confidence, signals=signals, evidence=ev.items, lead=lead,
                       identity_groups=identity, corroborating=corroborating, caps=caps,
                       coverage=round(coverage, 3), notify_eligible=lead in NOTIFY_LEADS)


def _v3_groups(signals: dict[str, float], feat_kinds: frozenset[str], model_shared: bool,
               identity_sim: float | None) -> tuple[list[str], list[str]]:
    """Split the matching attributes into identity-bearing groups and corroborating (generic) ones.

    Identity-bearing: shared model code; marking or damage feature; description similarity without
    generic wording. Corroborating: accessory or other feature; same brand; compatible colour.
    """
    identity, corroborating = [], []
    if model_shared:
        identity.append("model")
    if feat_kinds & IDENTITY_FEATURE_KINDS:
        identity.append("features")
    if identity_sim is not None and identity_sim >= DESCRIPTION_IDENTITY:
        identity.append("description")
    if feat_kinds - IDENTITY_FEATURE_KINDS:
        corroborating.append("accessory features")
    if signals.get("brand") == 1.0:
        corroborating.append("brand")
    if signals.get("color") == 1.0:
        corroborating.append("colour")
    return identity, corroborating


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
    return MatchResult(score=score, confidence=confidence, signals=signals, evidence=ev.items, lead=lead,
                       identity_groups=_identity_groups(signals), notify_eligible=lead in NOTIFY_LEADS)
