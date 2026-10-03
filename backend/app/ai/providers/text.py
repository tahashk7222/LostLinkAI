"""Local text embeddings: hashed word + character-trigram term-frequency vectors.

This is a lexical-semantic representation (robust to word order, plurals and small
spelling differences), not a neural language model. It requires no network access.
"""

import hashlib
import math
import re
from typing import Protocol

DIM = 512

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "my", "i", "it",
    "is", "was", "near", "around", "about", "has", "had", "have", "this", "that", "from", "by",
    "lost", "found", "item", "some", "very", "its", "be", "been", "were", "there", "which",
    # Roman-Urdu function words
    "mera", "meri", "mere", "ka", "ki", "ke", "hai", "tha", "thi", "mein", "main", "se", "par", "aur", "hua",
    "hui", "kahin", "paas", "liye", "wala", "wali", "gaya", "gayi", "kar", "ko", "ne", "yeh", "woh",
}


class TextEmbedder(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # crude singularisation: keys -> key
        out.append(w)
    return out


def _bucket(token: str) -> int:
    return int.from_bytes(hashlib.md5(token.encode()).digest()[:4], "little") % DIM


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


class HashingTextEmbedder:
    name = "hashing-ngram-v1"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for tok in tokenize(text):
            vec[_bucket("w:" + tok)] += 1.0
            padded = f"#{tok}#"
            for i in range(len(padded) - 2):
                vec[_bucket("c:" + padded[i : i + 3])] += 0.3
        norm = math.sqrt(sum(v * v for v in vec))
        return [round(v / norm, 5) for v in vec] if norm else vec
