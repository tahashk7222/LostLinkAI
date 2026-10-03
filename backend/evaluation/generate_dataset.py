"""Generate the SYNTHETIC lost/found evaluation dataset.

Every record is invented for evaluation. No real person, report or location
history is used. Coordinates come from the public campus place list
(app/geo/uet_lahore.json) so distances behave like the live system.

The output is deterministic (fixed seed). Re-running this script must reproduce
`synthetic_pairs.json` byte for byte; the evaluation results depend on it.

    python -m evaluation.generate_dataset
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEO_FILE = HERE.parent / "app" / "geo" / "uet_lahore.json"
OUT_FILE = HERE / "data" / "synthetic_pairs.json"
SEED = 20261003
N_TRUE_PAIRS = 50

# Each item type: form-field nouns that normalise to a canonical category,
# colour and brand choices, and distinctive features. Names always contain a
# canonical noun so category normalisation sees the same item the owner describes.
ITEMS = [
    dict(key="backpack", lost_category="Backpack", found_categories=["Bag", "Backpack"],
         nouns=["backpack", "school bag"], colors=["black", "navy blue", "grey", "maroon", "green"],
         brands=["JanSport", "Herschel", "Skybags", "Wildcraft", "Nike"],
         features=["red keychain on the front zipper", "name tag with initials inside",
                   "cricket team sticker on the front pocket", "torn left strap", "white tape on the handle"]),
    dict(key="wallet", lost_category="Wallet", found_categories=["Wallet", "Card holder"],
         nouns=["wallet", "card holder"], colors=["brown", "black", "tan"],
         brands=["Fossil", "Louis Vuitton", "Gucci"],
         features=["scratch on the back", "photo of a child in the card slot", "stitched initials on the front"]),
    dict(key="phone", lost_category="Phone", found_categories=["Phone", "Mobile", "Smartphone"],
         nouns=["phone", "smartphone"], colors=["black", "silver", "blue", "gold", "green"],
         brands=["Samsung", "Apple", "Oppo", "Infinix", "Tecno", "Xiaomi"],
         features=["cracked screen corner", "blue case with a sticker", "cricket player wallpaper",
                   "small dent on the frame"]),
    dict(key="keys", lost_category="Keys", found_categories=["Keys", "Key ring"],
         nouns=["keys", "car keys"], colors=["silver", "black"], brands=["Toyota", "Honda"],
         features=["football shaped keychain", "small torch attached to the ring",
                   "blue plastic tag with a number"]),
    dict(key="bottle", lost_category="Water bottle", found_categories=["Bottle", "Water bottle", "Flask"],
         nouns=["water bottle", "flask"], colors=["green", "silver", "blue", "pink"], brands=[],
         features=["stickers on the body", "dent near the bottom", "name written on the lid"]),
    dict(key="laptop", lost_category="Laptop", found_categories=["Laptop", "Macbook"],
         nouns=["laptop", "macbook"], colors=["silver", "grey", "black"],
         brands=["Dell", "HP", "Lenovo", "Acer", "Apple"],
         features=["sticker on the lid", "cracked corner of the screen", "missing rubber feet"]),
    dict(key="watch", lost_category="Watch", found_categories=["Watch", "Wristwatch"],
         nouns=["watch", "wristwatch"], colors=["black", "silver", "gold"],
         brands=["Casio", "Fossil", "Fitbit", "Titan"],
         features=["leather strap with a scratch", "engraved back cover"]),
    dict(key="earbuds", lost_category="Earbuds", found_categories=["Headphones", "Earphones"],
         nouns=["earbuds", "headphones"], colors=["white", "black", "red"],
         brands=["JBL", "Sony", "Bose", "Apple"],
         features=["one earbud has a green sticker", "charging case with a scratch on the lid"]),
    dict(key="id-card", lost_category="ID card", found_categories=["ID card", "Student card"],
         nouns=["student card", "id card"], colors=["green", "blue", "white"], brands=[],
         features=["name written with a marker", "photo partly torn"]),
    dict(key="jacket", lost_category="Jacket", found_categories=["Jacket", "Hoodie"],
         nouns=["jacket", "hoodie"], colors=["black", "grey", "navy blue", "maroon"],
         brands=["Nike", "Adidas", "Puma"],
         features=["zip pull replaced with a safety pin", "patch on the left sleeve"]),
]

LOST_TEMPLATES = [
    "I lost my {desc} near the {place} around {t}.",
    "Lost a {desc} somewhere around {place} at about {t}. Please contact me if it is found.",
    "Left my {desc} at {place} around {t} and could not find it again.",
]
FOUND_TEMPLATES = [
    "Found a {desc} near {place} at about {t}.",
    "Picked up a {desc} from {place} around {t}, kept it safe.",
    "A {desc} was left at {place} at {t}. Looking for the owner.",
]
PRIVATE_LINES = [
    "Inside: a notebook, a calculator and a water bottle.",
    "Contains two cards and a little cash.",
    "Serial number ends in 4821; sticker underneath is peeling.",
    "Has a hidden pocket with a small photo.",
    "Inner label has a handwritten code.",
]


def load_places() -> list[dict]:
    data = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    return [p for p in data["places"] if p["area"] != "sports"]  # keep the set to walkable academic spots


def clock(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'PM' if dt.hour >= 12 else 'AM'}"


def jitter(rng: random.Random, lat: float, lng: float, max_deg: float = 0.0012) -> tuple[float, float]:
    return round(lat + rng.uniform(-max_deg, max_deg), 6), round(lng + rng.uniform(-max_deg, max_deg), 6)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(item: dict, color: str | None, brand: str | None, noun: str) -> str:
    parts = [p for p in (color, brand, noun) if p]
    return " ".join(parts)


def make_report(rng, kind, item, *, color, brand, noun, feature, when, place, gps, desc_place_name, template,
                private=True):
    if gps:
        lat, lng = jitter(rng, place["lat"], place["lng"])
        loc = dict(location=f"Near {place['name']}", location_type="gps", place_key=None,
                   latitude=lat, longitude=lng, zone="campus")
    else:
        loc = dict(location=place["name"], location_type="predefined", place_key=place["key"],
                   latitude=place["lat"], longitude=place["lng"], zone="campus")
    desc = describe(item, color, brand, noun)
    text = template.format(desc=desc, place=desc_place_name, t=clock(when))
    if feature and rng.random() < 0.5:
        text += f" It has {feature}."
    row = dict(
        name=f"{(color or '').capitalize()} {noun}".strip().title(),
        category=(item["lost_category"] if kind == "LOST" else rng.choice(item["found_categories"])),
        description=text,
        color=color,
        brand=brand,
        distinctive_features=feature,
        private_details=rng.choice(PRIVATE_LINES) if private else None,
        date_time=iso(when),
        **loc,
    )
    return row


def build() -> dict:
    rng = random.Random(SEED)
    places = load_places()
    lost_rows, found_rows, true_pairs = [], [], []

    for i in range(N_TRUE_PAIRS):
        item = ITEMS[i % len(ITEMS)]
        noun = rng.choice(item["nouns"])
        color = rng.choice(item["colors"])
        brand = rng.choice(item["brands"]) if item["brands"] and rng.random() < 0.6 else None
        feature = rng.choice(item["features"])
        place = rng.choice(places)
        base = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 28),
                                                                       hours=rng.randint(8, 17))
        lost_when = base
        found_when = lost_when + timedelta(hours=round(rng.uniform(0.3, 20), 1))

        lost = make_report(rng, "LOST", item, color=color, brand=brand, noun=noun,
                           feature=feature if rng.random() < 0.5 else None, when=lost_when, place=place,
                           gps=False, desc_place_name=place["name"], template=rng.choice(LOST_TEMPLATES))
        # The finder sometimes omits the colour or brand, and may pick a nearby spot.
        f_color = color if rng.random() < 0.8 else None
        f_brand = brand if (brand and rng.random() < 0.5) else None
        f_feature = feature if rng.random() < 0.5 else None
        found = make_report(rng, "FOUND", item, color=f_color, brand=f_brand, noun=noun, feature=f_feature,
                            when=found_when, place=place, gps=True, desc_place_name=place["name"],
                            template=rng.choice(FOUND_TEMPLATES))
        lost_id = f"L{i + 1:03d}"
        lost.update(id=lost_id, role="owner_query", item_type=item["key"])
        found.update(role="true_match", origin=lost_id, item_type=item["key"])
        lost_rows.append(lost)
        found_rows.append(found)
        true_pairs.append((lost_id, found))

        # Hard negatives: look-alike items that a naive matcher could confuse with the true item.
        other_places = [p for p in places if p["key"] != place["key"]]
        other_item = rng.choice([x for x in ITEMS if x["key"] != item["key"]])
        hard = [
            # Same type, colour and brand, but a different item found elsewhere days later.
            ("hn-lookalike", dict(color=color, brand=brand, noun=noun, feature=None,
                                  when=lost_when + timedelta(days=rng.randint(2, 6)),
                                  place=rng.choice(other_places), gps=True)),
            # Same type and colour, different brand.
            ("hn-brand", dict(color=color, brand=_other_brand(rng, item, brand), noun=noun, feature=None,
                              when=lost_when + timedelta(hours=rng.randint(1, 10)), place=place, gps=True)),
            # Same type and brand, different colour.
            ("hn-colour", dict(color=_other_color(rng, item, color), brand=brand, noun=noun, feature=None,
                               when=lost_when + timedelta(hours=rng.randint(1, 5)), place=place, gps=True)),
            # Identical description, but the found time is before the loss.
            ("hn-before-loss", dict(color=color, brand=brand, noun=noun, feature=None,
                                    when=lost_when - timedelta(days=rng.randint(1, 3)), place=place, gps=True)),
            # Same colour at the same place, but a different kind of item.
            ("hn-category", dict(color=color, brand=None, noun=rng.choice(other_item["nouns"]), feature=None,
                                 when=lost_when + timedelta(hours=rng.randint(1, 5)), place=place, gps=True,
                                 item=other_item)),
        ]
        for kind_name, spec in hard:
            spec = dict(spec)
            spec_item = spec.pop("item", item)
            row = make_report(rng, "FOUND", spec_item, desc_place_name=spec["place"]["name"],
                              template=rng.choice(FOUND_TEMPLATES), private=True,
                              **{k: spec[k] for k in ("color", "brand", "noun", "feature", "when", "place", "gps")})
            row.update(role="hard_negative", origin=lost_id, negative_type=kind_name,
                       item_type=spec_item["key"])
            found_rows.append(row)

    # Easy negatives: unrelated found items, not linked to any query.
    for j in range(30):
        item = rng.choice(ITEMS)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 28), hours=rng.randint(8, 17))
        row = make_report(rng, "FOUND", item, color=rng.choice(item["colors"]), brand=None,
                          noun=rng.choice(item["nouns"]), feature=None, when=when,
                          place=rng.choice(places), gps=True, desc_place_name="campus",
                          template=rng.choice(FOUND_TEMPLATES))
        row.update(role="easy_negative", origin=None, negative_type="unrelated", item_type=item["key"])
        found_rows.append(row)

    # Sequential found ids, assigned once all rows exist (so ids never collide).
    for n, row in enumerate(found_rows, 1):
        row["id"] = f"F{n:03d}"
    true_pairs = [[lost_id, found["id"]] for lost_id, found in true_pairs]

    return {
        "dataset": "SYNTHETIC",
        "notice": ("Invented for offline evaluation. Not real user reports, people or locations history. "
                   "Coordinates are campus place points from app/geo/uet_lahore.json."),
        "generator": "backend/evaluation/generate_dataset.py",
        "seed": SEED,
        "counts": {"lost": len(lost_rows), "found": len(found_rows), "true_pairs": len(true_pairs)},
        "lost": lost_rows,
        "found": found_rows,
        "true_pairs": true_pairs,
    }


def _other_brand(rng, item, brand):
    options = [b for b in item["brands"] if b != brand]
    return rng.choice(options) if options else None


def _other_color(rng, item, color):
    options = [c for c in item["colors"] if c != color]
    return rng.choice(options)


def main() -> None:
    data = build()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT_FILE} {data['counts']}")


if __name__ == "__main__":
    main()
