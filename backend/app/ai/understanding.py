"""Item Understanding (deterministic rules, no learned model).

Normalises categories and extracts colours (with shades), brands (with aliases), model numbers,
and typed distinctive features from free text, including common Roman-Urdu words.

Every attribute records its origin:
- USER: a value the person typed into a form field
- RULE: inferred from free text by deterministic rules, with a confidence value

Legacy rows that were stored as "AI" before this change are rule-based too; migration 0004 relabels them.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.ai.providers.text import tokenize
from app.models.enums import AttributeSource

# canonical category -> (group, synonyms). Roman-Urdu synonyms are included where common.
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "backpack": ("bags", ["backpack", "rucksack", "school bag", "schoolbag", "knapsack", "bookbag"]),
    "handbag": ("bags", ["handbag", "purse", "tote", "clutch", "shoulder bag", "sling bag"]),
    "luggage": ("bags", ["suitcase", "luggage", "duffel", "duffle", "travel bag", "trolley bag"]),
    "laptop bag": ("bags", ["laptop bag", "laptop sleeve", "messenger bag", "briefcase"]),
    "wallet": ("wallets", ["wallet", "billfold", "card holder", "cardholder", "money clip", "batwa"]),
    "phone": ("electronics", ["phone", "mobile", "smartphone", "iphone", "cell phone", "cellphone", "android"]),
    "laptop": ("electronics", ["laptop", "notebook computer", "macbook", "chromebook"]),
    "tablet": ("electronics", ["tablet", "ipad"]),
    "headphones": ("electronics", ["headphones", "earphones", "earbuds", "airpods", "headset"]),
    "charger": ("electronics", ["charger", "power bank", "powerbank", "cable", "adapter"]),
    "watch": ("accessories", ["watch", "smartwatch", "wristwatch", "ghari"]),
    "keys": ("keys", ["keys", "key", "keychain", "key ring", "car key", "fob", "chabi", "chabiyan"]),
    "id card": ("documents", ["id card", "student card", "identity card", "cnic", "license", "licence", "passport",
                              "shanakhti card"]),
    "documents": ("documents", ["document", "documents", "file", "folder", "certificate"]),
    "glasses": ("accessories", ["glasses", "spectacles", "sunglasses", "eyeglasses", "chashma", "ainak"]),
    "jewelry": ("accessories", ["ring", "necklace", "bracelet", "earring", "jewelry", "jewellery", "chain"]),
    "clothing": ("clothing", ["jacket", "coat", "hoodie", "sweater", "scarf", "cap", "hat", "shirt", "gloves"]),
    "umbrella": ("other", ["umbrella", "chatri"]),
    "water bottle": ("other", ["water bottle", "bottle", "flask", "tumbler", "paani ki bottle"]),
    "book": ("other", ["book", "notebook", "diary", "textbook", "kitab"]),
}

# colour word -> family (kept for compatibility; SHADES adds the shade)
COLORS: dict[str, str] = {
    "black": "black", "jet black": "black", "kala": "black", "kali": "black", "kaala": "black", "kaali": "black",
    "charcoal": "gray", "gray": "gray", "grey": "gray", "silver": "gray", "chandi": "gray", "surmai": "gray",
    "white": "white", "ivory": "white", "cream": "white", "off-white": "white", "safed": "white", "safaid": "white",
    "red": "red", "maroon": "red", "burgundy": "red", "crimson": "red", "laal": "red",
    "blue": "blue", "navy": "blue", "navy blue": "blue", "sky blue": "blue", "teal": "blue", "turquoise": "blue",
    "neela": "blue", "neeli": "blue", "neelay": "blue",
    "green": "green", "olive": "green", "lime": "green", "mint": "green", "hara": "green", "hari": "green",
    "sabz": "green",
    "yellow": "yellow", "gold": "yellow", "golden": "yellow", "mustard": "yellow", "peela": "yellow",
    "peeli": "yellow", "sunehri": "yellow",
    "orange": "orange", "peach": "orange", "narangi": "orange",
    "pink": "pink", "rose": "pink", "magenta": "pink", "gulabi": "pink",
    "purple": "purple", "violet": "purple", "lavender": "purple", "jamuni": "purple",
    "brown": "brown", "tan": "brown", "beige": "brown", "khaki": "brown", "leather": "brown",
    "bhoora": "brown", "bhora": "brown", "bhoori": "brown",
}

# (family, shade) for the colour words where a shade is stated explicitly
SHADES: dict[str, tuple[str, str]] = {
    "navy": ("blue", "dark"), "navy blue": ("blue", "dark"), "sky blue": ("blue", "light"),
    "dark blue": ("blue", "dark"), "light blue": ("blue", "light"), "neelay": ("blue", "plain"),
    "maroon": ("red", "dark"), "burgundy": ("red", "dark"), "crimson": ("red", "vivid"),
    "dark grey": ("gray", "dark"), "dark gray": ("gray", "dark"), "light grey": ("gray", "light"),
    "light gray": ("gray", "light"), "charcoal": ("gray", "dark"), "silver": ("gray", "metallic"),
    "chandi": ("gray", "metallic"), "gold": ("yellow", "metallic"), "golden": ("yellow", "metallic"),
    "sunehri": ("yellow", "metallic"), "dark green": ("green", "dark"), "light green": ("green", "light"),
    "olive": ("green", "dark"), "mint": ("green", "light"), "dark brown": ("brown", "dark"),
    "light brown": ("brown", "light"), "tan": ("brown", "light"), "beige": ("brown", "light"),
    "khaki": ("brown", "light"), "off-white": ("white", "off"), "cream": ("white", "off"),
    "ivory": ("white", "off"), "pink": ("pink", "plain"), "hot pink": ("pink", "vivid"),
}

# Colour families that are visually close: partial compatibility rather than a conflict.
NEAR_FAMILIES: set[frozenset[str]] = {
    frozenset(p) for p in [
        ("black", "gray"), ("white", "gray"), ("brown", "orange"), ("brown", "yellow"),
        ("red", "pink"), ("red", "orange"), ("blue", "purple"), ("blue", "green"), ("yellow", "orange"),
        ("yellow", "green"), ("brown", "gray"), ("pink", "purple"),
    ]
}

# alias (lowercase, as typed) -> canonical brand
BRAND_ALIASES: dict[str, str] = {
    "jan sport": "jansport", "janspot": "jansport", "janssport": "jansport",
    "north face": "the north face", "the north face": "the north face",
    "ray ban": "ray-ban", "rayban": "ray-ban", "ray-ban": "ray-ban",
    "one plus": "oneplus", "one-plus": "oneplus", "oneplus": "oneplus",
    "hewlett packard": "hp", "hewlett-packard": "hp", "hp": "hp",
    "american tourister": "american tourister", "under armour": "under armour",
    "iphone": "apple", "ipad": "apple", "macbook": "apple", "airpods": "apple", "apple": "apple",
    "galaxy": "samsung", "samsung": "samsung", "redmi": "xiaomi", "poco": "xiaomi", "xiaomi": "xiaomi",
    "oppo": "oppo", "vivo": "vivo", "infinix": "infinix", "tecno": "tecno",
    "realme": "realme", "huawei": "huawei", "nokia": "nokia", "motorola": "motorola", "moto": "motorola",
    "sony": "sony", "lenovo": "lenovo", "dell": "dell", "asus": "asus", "acer": "acer", "msi": "msi",
    "microsoft": "microsoft", "jbl": "jbl", "bose": "bose", "beats": "beats", "anker": "anker",
    "nike": "nike", "adidas": "adidas", "puma": "puma", "reebok": "reebok", "jansport": "jansport",
    "herschel": "herschel", "samsonite": "samsonite", "wildcraft": "wildcraft", "skybags": "skybags",
    "gucci": "gucci", "louis vuitton": "louis vuitton", "casio": "casio", "rolex": "rolex", "fossil": "fossil",
    "titan": "titan", "fitbit": "fitbit", "garmin": "garmin",
}

# Model-number patterns. Names followed by an alphanumeric model (iPhone 13, Galaxy A52, Pixel 7a) and
# bare model codes with a letter prefix and digits (SM-A525F, XPS13, F-91W). Times such as "5pm" are excluded.
MODEL_NAME_RE = re.compile(
    r"\b(iphone|galaxy|pixel|redmi|poco|macbook|thinkpad|ideapad|inspiron|xps|pavilion|spectre|casio|jbl|nokia|moto)"
    r"[\s-]*([a-z]{0,3}\d{1,4}[a-z]{0,3})\b")
MODEL_CODE_RE = re.compile(r"\b([a-z]{1,4}-[a-z]{0,2}\d{2,5}[a-z]{0,2})\b")
MODEL_STOP = {"am", "pm"}

# Typed distinctive features. Each cue has one type; the type decides which features can be compared.
FEATURE_TYPES: dict[str, list[str]] = {
    "accessory": ["keychain", "key chain", "charm", "key ring", "lanyard", "pouch", "cover", "case", "pendant",
                  "strap", "chabi"],
    "marking": ["sticker", "name tag", "tag", "initials", "engraved", "engraving", "badge", "label", "logo",
                "marker", "pin", "embroidered", "signature", "name written", "name on"],
    "damage": ["scratch", "crack", "dent", "stain", "patch", "torn", "tear", "broken", "worn", "chipped", "faded",
               "burn", "zip broken", "zipper broken"],
    "other": ["zip", "zipper", "pocket", "tape", "ribbon", "mark", "chain"],
}
FEATURE_CUES = [(cue, ftype) for ftype, cues in FEATURE_TYPES.items() for cue in cues]

FEATURE_CUES_WORDS = [cue for cue, _ in FEATURE_CUES]

# Roman-Urdu and English function words ignored by similarity comparisons
FEATURE_STOP = {"on", "the", "a", "an", "with", "and", "has", "have", "it", "its", "of", "in", "at", "is", "was",
                "ka", "ki", "ke", "hai", "tha", "mein", "par", "aur", "wala", "wali", "se", "back", "front"}


@dataclass
class ExtractedAttribute:
    name: str
    value: str
    source: AttributeSource
    confidence: float


@dataclass(frozen=True)
class TypedFeature:
    kind: str  # accessory | marking | damage | other
    phrase: str
    tokens: frozenset[str]  # content words, colour words included
    colors: frozenset[str]  # colour families mentioned inside the feature phrase


@dataclass
class Understanding:
    category: str  # canonical
    category_group: str
    colors: set[str]  # families
    brand: str | None
    features: list[str]
    attributes: list[ExtractedAttribute]
    shades: set[tuple[str, str]] = field(default_factory=set)
    models: list[str] = field(default_factory=list)  # normalised, e.g. "iphone13"
    typed_features: list[TypedFeature] = field(default_factory=list)


@lru_cache(maxsize=1)
def structured_terms() -> frozenset[str]:
    """Words that structured signals already cover (category, colour, brand, model, feature cues).

    The description signal removes these so the same evidence is not counted twice."""
    phrases: set[str] = set(COLORS) | set(SHADES) | set(BRAND_ALIASES) | set(FEATURE_CUES_WORDS)
    for canon, (_, synonyms) in CATEGORIES.items():
        phrases.update(synonyms + [canon])
    phrases.update({"iphone", "galaxy", "pixel", "redmi", "poco", "macbook", "thinkpad", "ideapad", "inspiron",
                    "xps", "pavilion", "spectre", "casio"})
    terms: set[str] = set()
    for ph in phrases:
        terms.update(tokenize(ph))
    return frozenset(terms)


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


def extract_color_shades(text: str) -> set[tuple[str, str]]:
    """(family, shade) pairs. A word without a stated shade gets shade 'plain'."""
    t = text.lower()
    matched = [w for w in set(COLORS) | set(SHADES) if _contains(t, w)]
    # "dark blue" also contains "blue": keep only the most specific phrase.
    specific = [w for w in matched if not any(w != o and _contains(o, w) for o in matched)]
    out: set[tuple[str, str]] = set()
    for word in specific:
        family = COLORS[word] if word in COLORS else SHADES[word][0]
        out.add(SHADES.get(word, (family, "plain")))
    return out


def color_compatibility(a: set[str], b: set[str]) -> tuple[str, float] | None:
    """Compare two sets of colour families.

    Returns ("same", 1.0) when they share a family, ("near", 0.5) when a family is visually close
    to one on the other side, ("conflict", 0.0) otherwise. None when either side has no colour.
    """
    if not a or not b:
        return None
    if a & b:
        return "same", 1.0
    if any(frozenset((x, y)) in NEAR_FAMILIES for x in a for y in b):
        return "near", 0.5
    return "conflict", 0.0


def extract_brand(text: str) -> str | None:
    t = text.lower()
    found = [alias for alias in BRAND_ALIASES if _contains(t, alias)]
    if not found:
        return None
    return BRAND_ALIASES[max(found, key=len)]


def normalize_brand(value: str) -> str:
    """Canonical brand for a form-field value (alias-aware, falls back to the cleaned value)."""
    v = re.sub(r"\s+", " ", value.lower().strip())
    return BRAND_ALIASES.get(v, v)


def extract_models(text: str) -> list[str]:
    t = text.lower()
    found: list[str] = []
    for m in MODEL_NAME_RE.finditer(t):
        code = m.group(2)
        if code and code not in MODEL_STOP and any(ch.isdigit() for ch in code):
            found.append(f"{m.group(1)}{code}")
    for m in MODEL_CODE_RE.finditer(t):
        found.append(m.group(1).replace("-", ""))
    return list(dict.fromkeys(found))


def normalize_model(value: str) -> str:
    return re.sub(r"[\s\-]+", "", value.lower())


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w for w in words if w not in FEATURE_STOP and len(w) > 1)


def extract_typed_features(text: str) -> list[TypedFeature]:
    """Phrases around feature cues, each tagged with a feature type (accessory, marking, damage)."""
    t = text.lower()
    out: list[TypedFeature] = []
    seen: set[str] = set()
    for sentence in re.split(r"[.;,\n]|\band\b", t):
        for cue, ftype in FEATURE_CUES:
            if _contains(sentence, cue):
                phrase = sentence.strip()
                if 3 <= len(phrase) <= 120 and phrase not in seen:
                    seen.add(phrase)
                    colors = frozenset(COLORS[w] for w in COLORS if _contains(phrase, w))
                    out.append(TypedFeature(ftype, phrase, _tokens(phrase), colors))
                break
    return out[:6]


def extract_features(text: str) -> list[str]:
    """Short phrases around feature cue words, e.g. 'red keychain', 'scratch on the back'."""
    return [f.phrase for f in extract_typed_features(text)]


def understand(report) -> Understanding:
    """Analyse an ItemReport-like object (category, name, description, color, brand, model, distinctive_features)."""
    attrs: list[ExtractedAttribute] = []
    free_text = " ".join(filter(None, [report.name, report.description, report.distinctive_features]))

    cat, group, conf = normalize_category(f"{report.category} {report.name}")
    if cat == normalize_category(report.category)[0]:
        attrs.append(ExtractedAttribute("category", cat, AttributeSource.USER, 1.0))
    else:
        attrs.append(ExtractedAttribute("category", cat, AttributeSource.RULE, conf))

    colors: set[str] = set()
    shades: set[tuple[str, str]] = set()
    if report.color:
        colors = extract_colors(report.color) or {report.color.lower().strip()}
        shades = extract_color_shades(report.color)
        for c in sorted(colors):
            attrs.append(ExtractedAttribute("color", c, AttributeSource.USER, 1.0))
    inferred_colors = extract_colors(free_text) - colors
    for c in sorted(inferred_colors):
        attrs.append(ExtractedAttribute("color", c, AttributeSource.RULE, 0.7))
    # A user-entered colour describes the item itself; colours inferred from free text may
    # belong to accessories ("red keychain"), so they are only used when no colour was given.
    if not colors:
        colors = inferred_colors
        shades = extract_color_shades(free_text)

    brand = normalize_brand(report.brand) if report.brand and report.brand.strip() else None
    if brand:
        attrs.append(ExtractedAttribute("brand", brand, AttributeSource.USER, 1.0))
    else:
        brand = extract_brand(free_text)
        if brand:
            attrs.append(ExtractedAttribute("brand", brand, AttributeSource.RULE, 0.75))

    models: list[str] = []
    if report.model and report.model.strip():
        models.append(normalize_model(report.model))
        attrs.append(ExtractedAttribute("model", report.model.strip(), AttributeSource.USER, 1.0))
    else:
        for m in extract_models(free_text):
            models.append(m)
            attrs.append(ExtractedAttribute("model", m, AttributeSource.RULE, 0.6))

    typed = extract_typed_features(free_text)
    features = [f.phrase for f in typed]
    for f in features:
        src = AttributeSource.USER if report.distinctive_features and f in report.distinctive_features.lower() \
            else AttributeSource.RULE
        attrs.append(ExtractedAttribute("feature", f, src, 1.0 if src == AttributeSource.USER else 0.6))

    return Understanding(cat, group, colors, brand, features, attrs, shades, models, typed)


def embedding_text(report) -> str:
    """Public text used for semantic comparison (never includes private details)."""
    return " ".join(
        filter(None, [report.category, report.name, report.description, report.color, report.brand,
                      report.model, report.distinctive_features])
    )
