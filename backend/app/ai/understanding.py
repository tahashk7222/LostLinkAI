"""Item Understanding Agent (rule-based MVP).

Normalises categories and extracts colours, brands and distinctive features from
free text. Every attribute records whether it came from the USER (a form field)
or was inferred by the system (AI) with a confidence value.
"""

import re
from dataclasses import dataclass

from app.models.enums import AttributeSource

# canonical category -> (group, synonyms)
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "backpack": ("bags", ["backpack", "rucksack", "school bag", "schoolbag", "knapsack", "bookbag"]),
    "handbag": ("bags", ["handbag", "purse", "tote", "clutch", "shoulder bag", "sling bag"]),
    "luggage": ("bags", ["suitcase", "luggage", "duffel", "duffle", "travel bag", "trolley bag"]),
    "laptop bag": ("bags", ["laptop bag", "laptop sleeve", "messenger bag", "briefcase"]),
    "wallet": ("wallets", ["wallet", "billfold", "card holder", "cardholder", "money clip"]),
    "phone": ("electronics", ["phone", "mobile", "smartphone", "iphone", "cell phone", "cellphone", "android"]),
    "laptop": ("electronics", ["laptop", "notebook computer", "macbook", "chromebook"]),
    "tablet": ("electronics", ["tablet", "ipad"]),
    "headphones": ("electronics", ["headphones", "earphones", "earbuds", "airpods", "headset"]),
    "charger": ("electronics", ["charger", "power bank", "powerbank", "cable", "adapter"]),
    "watch": ("accessories", ["watch", "smartwatch", "wristwatch"]),
    "keys": ("keys", ["keys", "key", "keychain", "key ring", "car key", "fob"]),
    "id card": ("documents", ["id card", "student card", "identity card", "cnic", "license", "licence", "passport"]),
    "documents": ("documents", ["document", "documents", "file", "folder", "certificate"]),
    "glasses": ("accessories", ["glasses", "spectacles", "sunglasses", "eyeglasses"]),
    "jewelry": ("accessories", ["ring", "necklace", "bracelet", "earring", "jewelry", "jewellery", "chain"]),
    "clothing": ("clothing", ["jacket", "coat", "hoodie", "sweater", "scarf", "cap", "hat", "shirt", "gloves"]),
    "umbrella": ("other", ["umbrella"]),
    "water bottle": ("other", ["water bottle", "bottle", "flask", "tumbler"]),
    "book": ("other", ["book", "notebook", "diary", "textbook"]),
}

# colour word -> family
COLORS: dict[str, str] = {
    "black": "black", "jet black": "black", "charcoal": "gray",
    "white": "white", "ivory": "white", "cream": "white", "off-white": "white",
    "gray": "gray", "grey": "gray", "silver": "gray",
    "red": "red", "maroon": "red", "burgundy": "red", "crimson": "red",
    "blue": "blue", "navy": "blue", "navy blue": "blue", "sky blue": "blue", "teal": "blue", "turquoise": "blue",
    "green": "green", "olive": "green", "lime": "green", "mint": "green",
    "yellow": "yellow", "gold": "yellow", "golden": "yellow", "mustard": "yellow",
    "orange": "orange", "peach": "orange",
    "pink": "pink", "rose": "pink", "magenta": "pink",
    "purple": "purple", "violet": "purple", "lavender": "purple",
    "brown": "brown", "tan": "brown", "beige": "brown", "khaki": "brown", "leather": "brown",
}

BRANDS = [
    "apple", "samsung", "xiaomi", "oppo", "vivo", "infinix", "tecno", "realme", "huawei", "oneplus", "google",
    "nokia", "motorola", "sony", "lenovo", "dell", "hp", "asus", "acer", "msi", "microsoft", "jbl", "bose",
    "beats", "anker", "nike", "adidas", "puma", "reebok", "under armour", "jansport", "herschel", "samsonite",
    "american tourister", "north face", "the north face", "wildcraft", "skybags", "gucci", "louis vuitton",
    "casio", "rolex", "fossil", "titan", "ray-ban", "rayban", "fitbit", "garmin", "toyota", "honda", "suzuki",
]

FEATURE_CUES = [
    "sticker", "keychain", "key chain", "scratch", "crack", "dent", "stain", "patch", "badge", "tag", "name tag",
    "engraved", "engraving", "initials", "logo", "torn", "broken", "zip", "zipper", "pocket", "strap", "charm",
    "pin", "embroidered", "case", "cover", "tape", "mark", "label", "ribbon", "chain",
]


@dataclass
class ExtractedAttribute:
    name: str
    value: str
    source: AttributeSource
    confidence: float


@dataclass
class Understanding:
    category: str  # canonical
    category_group: str
    colors: set[str]  # families
    brand: str | None
    features: list[str]
    attributes: list[ExtractedAttribute]


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def normalize_category(text: str) -> tuple[str, str, float]:
    """Return (canonical category, group, confidence). Longest synonym wins."""
    t = text.lower()
    best: tuple[str, str, int] | None = None
    for canon, (group, synonyms) in CATEGORIES.items():
        for syn in synonyms + [canon]:
            if _contains(t, syn) and (best is None or len(syn) > best[2]):
                best = (canon, group, len(syn))
    if best:
        return best[0], best[1], 0.9
    return t.strip()[:50] or "other", "other", 0.3


def category_group(category: str) -> str:
    entry = CATEGORIES.get(category.lower())
    return entry[0] if entry else normalize_category(category)[1]


def extract_colors(text: str) -> set[str]:
    t = text.lower()
    return {family for word, family in COLORS.items() if _contains(t, word)}


def extract_brand(text: str) -> str | None:
    t = text.lower()
    found = [b for b in BRANDS if _contains(t, b)]
    return max(found, key=len) if found else None


def extract_features(text: str) -> list[str]:
    """Short phrases around feature cue words, e.g. 'red keychain', 'scratch on the back'."""
    t = text.lower()
    phrases = []
    for sentence in re.split(r"[.;,\n]|\band\b", t):
        if any(_contains(sentence, cue) for cue in FEATURE_CUES):
            s = sentence.strip()
            if 3 <= len(s) <= 120:
                phrases.append(s)
    return phrases[:6]


def understand(report) -> Understanding:
    """Analyse an ItemReport-like object (category, name, description, color, brand, model, distinctive_features)."""
    attrs: list[ExtractedAttribute] = []
    free_text = " ".join(filter(None, [report.name, report.description, report.distinctive_features]))

    cat, group, conf = normalize_category(f"{report.category} {report.name}")
    if cat == normalize_category(report.category)[0]:
        attrs.append(ExtractedAttribute("category", cat, AttributeSource.USER, 1.0))
    else:
        attrs.append(ExtractedAttribute("category", cat, AttributeSource.AI, conf))

    colors: set[str] = set()
    if report.color:
        colors = extract_colors(report.color) or {report.color.lower().strip()}
        for c in sorted(colors):
            attrs.append(ExtractedAttribute("color", c, AttributeSource.USER, 1.0))
    inferred_colors = extract_colors(free_text) - colors
    for c in sorted(inferred_colors):
        attrs.append(ExtractedAttribute("color", c, AttributeSource.AI, 0.7))
    # A user-entered colour describes the item itself; colours inferred from free text may
    # belong to accessories ("red keychain"), so they are only used when no colour was given.
    if not colors:
        colors = inferred_colors

    brand = report.brand.lower().strip() if report.brand else None
    if brand:
        attrs.append(ExtractedAttribute("brand", brand, AttributeSource.USER, 1.0))
    else:
        brand = extract_brand(free_text)
        if brand:
            attrs.append(ExtractedAttribute("brand", brand, AttributeSource.AI, 0.75))
    if report.model:
        attrs.append(ExtractedAttribute("model", report.model.strip(), AttributeSource.USER, 1.0))

    features = extract_features(free_text)
    for f in features:
        src = AttributeSource.USER if report.distinctive_features and f in report.distinctive_features.lower() else AttributeSource.AI
        attrs.append(ExtractedAttribute("feature", f, src, 1.0 if src == AttributeSource.USER else 0.6))

    return Understanding(cat, group, colors, brand, features, attrs)


def embedding_text(report) -> str:
    """Public text used for semantic comparison (never includes private details)."""
    return " ".join(
        filter(None, [report.category, report.name, report.description, report.color, report.brand,
                      report.model, report.distinctive_features])
    )
