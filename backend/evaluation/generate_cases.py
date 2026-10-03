"""Generate the SYNTHETIC identity-case set: one case per kind of evidence the policy must judge.

Every record is invented, like the other evaluation sets. The output is deterministic (its own fixed seed) and is
written once. The original sets and `synthetic_pairs_targeted.json` are not touched.

Each case has five queries. Each query has its own feature text (its own serial, initials, engraving, or sticker),
so two queries in the same case never share an identical true match. A shared identifier only comes from the hard
negatives below, which are built on purpose.

Each lost query has a `case` label, and so does its true match, so recall is reported per case. Hard negatives
carry `negative_type`.

True-match cases:
  tc-unique-number        a label with a serial number (marking with digits)
  tc-engraving            an engraved name and number (marking with digits)
  tc-initials             initials inside a pocket (marking with initials)
  tc-unique-sticker       a sticker with a specific picture (marking, no digits or name)
  tc-generic-sticker      a team or club sticker (marking, common)
  tc-damage               a scratch, dent, crack or tear (damage)
  tc-custom-accessory     a customised keychain with a numbered tag (accessory, customised, with digits)
  tc-generic-accessory    a coloured keychain (accessory, common)
  tc-common-brand         brand and colour only (no feature, no description identity)
  tc-common-brand-unique-feature  common brand plus an engraved code (marking with digits)

Hard negatives (each a different physical item):
  tg-same-attrs-other               same category, colour and place; nothing identifying
  tg-common-brand-other             same brand and colour and place; a different feature
  tg-different-brand-same-feature   same feature and colour; a different brand
  tg-same-feature-other-category    same feature and colour and place; a different item category
  tg-same-feature-far               same category, colour and feature; a place about 1.5 km or more away
  tg-same-feature-same-cat-loc      same category, colour, feature and place; no brand on the found side (the
                                    control for "marking + category + location": nothing conflicts)

    python -m evaluation.generate_cases
"""

import json
import random
from datetime import datetime, timedelta, timezone

from evaluation.generate_dataset import HERE, load_places
from evaluation.generate_targeted import ITEMS, _found, _hard_negatives, _lost

OUT_FILE = HERE / "data" / "synthetic_pairs_cases.json"
SEED = 20261005
QUERIES_PER_CASE = 5

CASES = {
    "tc-unique-number": dict(item="phone", brand="Infinix", features=[
        "label with serial 4821 under the back cover", "label with serial 1837 under the back cover",
        "label with serial 9075 under the back cover", "label with serial 2216 under the back cover",
        "label with serial 6643 under the back cover"]),
    "tc-engraving": dict(item="watch", brand="Titan", features=[
        "engraved 'AYESHA 2019' on the back cover", "engraved 'BILAL 2018' on the back cover",
        "engraved 'HINA 2020' on the back cover", "engraved 'OMAR 7' on the back cover",
        "engraved 'SANA 11' on the back cover"]),
    "tc-initials": dict(item="backpack", brand="JanSport", features=[
        "initials AK inside the front pocket", "initials MR inside the front pocket",
        "initials SH inside the front pocket", "initials HA inside the front pocket",
        "initials ZB inside the front pocket"]),
    "tc-unique-sticker": dict(item="phone", brand="Samsung", features=[
        "sticker of a red dragon on the back", "sticker of a blue whale on the lid",
        "sticker of a yellow sun and a moon", "sticker of a purple owl on the back",
        "sticker of a white horse with a star"]),
    "tc-generic-sticker": dict(item="backpack", brand="Herschel", features=[
        "cricket team sticker on the front pocket", "football club sticker on the front pocket",
        "music band sticker on the front pocket", "flag sticker on the front pocket",
        "star sticker on the front pocket"]),
    "tc-damage": dict(item="watch", brand="Fossil", features=[
        "long diagonal scratch across the front glass", "deep dent near the lower corner",
        "crack along the top edge", "torn stitching on the left strap", "chipped paint near the hinge"]),
    "tc-custom-accessory": dict(item="keys", brand="Honda", features=[
        "custom keychain with a red leather tag number 17", "custom keychain with a blue tag number 42",
        "customised keychain with a brass charm 9", "custom keychain with a white tag number 88",
        "customised keychain with a green tag number 5"]),
    "tc-generic-accessory": dict(item="backpack", brand="Skybags", features=[
        "red keychain on the zipper", "black keychain on the zipper", "blue keychain on the zipper",
        "white keychain on the zipper", "green keychain on the zipper"]),
    "tc-common-brand": dict(item="keys", brand="Toyota", features=[]),
    "tc-common-brand-unique-feature": dict(item="watch", brand="Casio", features=[
        "engraved AK-19 on the back cover", "engraved BT-07 on the back cover", "engraved XR-33 on the back cover",
        "engraved LM-52 on the back cover", "engraved QZ-18 on the back cover"]),
}
ITEM_KEYS = list(ITEMS)
# Control features for "a different feature": typed, but sharing no same-kind overlap with any case feature.
# tests/test_eval_cases.py checks this against every case feature, so it cannot drift.
CONTROL_FEATURES = ["worn zip on the side", "pocket with a broken zip", "stain on the left side",
                    "tape on the handle", "ribbon tied to the top loop"]


def _distance2(a, b) -> float:
    return (a["lat"] - b["lat"]) ** 2 + (a["lng"] - b["lng"]) ** 2


def _far_place(places, place):
    """A campus place about 1.5 km or more away, or the farthest one available."""
    far = [p for p in places if p["key"] != place["key"] and _distance2(p, place) > (0.0135 ** 2)]
    pool = far or [p for p in places if p["key"] != place["key"]]
    return max(pool, key=lambda p: _distance2(p, place))


def _true_pair(rng, case, spec, q_id, place, when):
    it = ITEMS[spec["item"]]
    color = rng.choice(it["colors"])
    t_found = when + timedelta(hours=rng.randint(1, 12))
    brand = spec["brand"]
    feature = spec["feature"]
    desc_l = f"Lost my {color} {brand} {it['noun']} near {place['name']} around {when.hour % 12 or 12}.".replace("  ", " ")
    desc_f = f"Found a {color} {brand} {it['noun']} near {place['name']} at about {t_found.hour % 12 or 12}.".replace("  ", " ")
    lost = _lost(rng, qid=q_id, case=case, item_key=spec["item"], color=color, brand=brand,
                 feature=feature, desc=desc_l, when=when, place=place)
    found = _found(rng, case=case, role="true_match", item_key=spec["item"], color=color, brand=brand,
                   feature=feature, desc=desc_f, when=t_found, place=place, origin=q_id)
    return lost, found


def _extra_hard(rng, spec, q_id, color, place, when, places):
    """The three feature-control hard negatives. Skipped when the query has no distinctive feature."""
    if not spec["feature"]:
        return []
    it_key = spec["item"]
    other_item_key = rng.choice([k for k in ITEM_KEYS if k != it_key])
    out = [_found(rng, case="tg-same-feature-other-category", role="hard_negative", item_key=other_item_key,
                  color=color, brand=None, feature=spec["feature"],
                  desc=f"Found a {color} {ITEMS[other_item_key]['noun']} near {place['name']}.",
                  when=when + timedelta(hours=rng.randint(2, 8)), place=place, origin=q_id,
                  negative_type="tg-same-feature-other-category",
                  category=ITEMS[other_item_key]["found_categories"][0])]
    far = _far_place(places, place)
    out.append(_found(rng, case="tg-same-feature-far", role="hard_negative", item_key=it_key, color=color, brand=None,
                      feature=spec["feature"], desc=f"Found a {color} {ITEMS[it_key]['noun']} near {far['name']}.",
                      when=when + timedelta(hours=rng.randint(2, 8)), place=far, origin=q_id,
                      negative_type="tg-same-feature-far"))
    # The found report omits the brand, so nothing conflicts: only the marking, colour, category and place agree.
    out.append(_found(rng, case="tg-same-feature-same-cat-loc", role="hard_negative", item_key=it_key, color=color,
                      brand=None, feature=spec["feature"],
                      desc=f"Found a {color} {ITEMS[it_key]['noun']} near {place['name']} at about 3 PM.",
                      when=when + timedelta(hours=rng.randint(2, 8)), place=place, origin=q_id,
                      negative_type="tg-same-feature-same-cat-loc"))
    return out


def build() -> dict:
    rng = random.Random(SEED)
    places = load_places()
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    lost_rows, found_rows = [], []
    n = 0
    for case, spec in CASES.items():
        for k in range(QUERIES_PER_CASE):
            n += 1
            q_id = f"L{n:03d}"
            feature = spec["features"][k] if spec["features"] else None
            qspec = dict(spec, feature=feature)
            place = rng.choice(places)
            when = base + timedelta(days=rng.randint(0, 28), hours=rng.randint(8, 17))
            lost, found = _true_pair(rng, case, qspec, q_id, place, when)
            lost_rows.append(lost)
            found_rows.append(found)
            others = [p for p in places if p["key"] != place["key"]]
            hard = _hard_negatives(rng, q_id, lost["color"], spec["item"], spec["brand"], feature, place, when, others)
            for row in hard:  # a "different feature" must share no words with the query's feature
                if row["negative_type"] == "tg-common-brand-other":
                    row["distinctive_features"] = rng.choice(CONTROL_FEATURES)
            found_rows.extend(hard)
            found_rows.extend(_extra_hard(rng, qspec, q_id, lost["color"], place, when, places))
    for _ in range(30):
        key = rng.choice(ITEM_KEYS)
        when_e = base + timedelta(days=rng.randint(0, 28), hours=rng.randint(8, 17))
        color = rng.choice(ITEMS[key]["colors"])
        found_rows.append(_found(rng, case="unrelated", role="easy_negative", item_key=key, color=color, brand=None,
                                 feature=None, desc=f"Found a {color} {ITEMS[key]['noun']} near campus.",
                                 when=when_e, place=rng.choice(places), negative_type="unrelated"))

    for i, row in enumerate(found_rows, 1):
        row["id"] = f"F{i:03d}"
    true_pairs = [[r["origin"], r["id"]] for r in found_rows if r["role"] == "true_match"]
    return {
        "dataset": "SYNTHETIC",
        "notice": ("Invented for offline evaluation. Not real user reports, people or locations history. "
                   "Coordinates are campus place points from app/geo/uet_lahore.json. Photos are rendered "
                   "from simple synthetic shapes. Designed identity cases, not a random sample."),
        "generator": "backend/evaluation/generate_cases.py",
        "seed": SEED,
        "counts": {"lost": len(lost_rows), "found": len(found_rows), "true_pairs": len(true_pairs)},
        "lost": lost_rows,
        "found": found_rows,
        "true_pairs": true_pairs,
    }


def main() -> None:
    data = build()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT_FILE} {data['counts']}")


if __name__ == "__main__":
    main()
