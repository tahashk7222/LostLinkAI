"""Lexical retrieval and description similarity with BM25 (Okapi), pure Python.

Why BM25: a rare identifying term ("calculus", "gujranwala", "bhatti") should count for more than a
generic one ("bag", "black"). IDF gives that weight. Term frequency saturates, and long descriptions
are normalised by length.

Normalisation: a raw BM25 score is unbounded, so each score is divided by the largest score this
query could reach (every query term matched at full saturation). The result lies in [0, 1] and is a
rank-and-overlap measure, not a probability.

Only the free-text description is scored here. Category, colour, brand, model and typed
distinctive features have their own signals, so their words are removed from the description first.
"""

import math
from collections import Counter
from functools import lru_cache

from app.ai.providers.text import tokenize

K1 = 1.2
B = 0.75


class BM25Index:
    """Corpus statistics (document frequency and average length) for a small set of documents."""

    def __init__(self, docs: list[list[str]], k1: float = K1, b: float = B) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.df = df

    def idf(self, term: str) -> float:
        f = self.df.get(term, 0)
        return math.log(1 + (self.n - f + 0.5) / (f + 0.5))

    def _raw(self, query: list[str], doc: list[str]) -> float:
        q_terms = set(query)
        tf = Counter(doc)
        dl = len(doc)
        norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
        raw = 0.0
        for t in q_terms:
            f = tf.get(t, 0)
            if f:
                raw += self.idf(t) * f * (self.k1 + 1) / (f + norm)
        return raw

    def normalized(self, query: list[str], doc: list[str]) -> float:
        """BM25 of `doc` for `query`, divided by the query's score against itself. Returns a value in [0, 1].

        Identical descriptions score 1.0. A document that shares only generic terms scores low, because
        those terms carry little IDF weight.
        """
        if not query or not doc:
            return 0.0
        best = self._raw(query, query)
        if best <= 0:
            return 0.0
        return round(min(1.0, self._raw(query, doc) / best), 3)


def pair_similarity(index: BM25Index, lost, found, exclude: frozenset[str] = frozenset()) -> float | None:
    """Description similarity for one pair. The lost description is the query (the owner's wording).

    `exclude` removes words from both descriptions before comparing (scoring v3 removes accessory wording
    this way, so a shared keychain does not count as identity). Returns None when either side has no terms
    left: nothing was compared, so the signal is absent. That is different from 0, which means the
    descriptions were compared and share nothing.
    """
    q = [t for t in description_terms(lost) if t not in exclude]
    d = [t for t in description_terms(found) if t not in exclude]
    if not q or not d:
        return None
    return index.normalized(q, d)


# Report boilerplate and time words: they say how the item was reported, not what the item is.
BOILERPLATE = {
    "lost", "found", "please", "contact", "somewhere", "around", "time", "could", "find", "again", "left",
    "picked", "kept", "safe", "looking", "owner", "gave", "near", "about", "at", "item", "report", "reported",
    "notice", "noticed", "seen", "saw", "today", "yesterday", "morning", "evening", "afternoon", "night",
    "pm", "am", "thanks", "thank", "kindly", "dear", "hi", "outside", "bench", "from", "there", "this", "was",
    "have", "had", "will", "photo", "pic", "me", "my", "it", "if", "is", "the", "one",
}


@lru_cache(maxsize=1)
def location_terms() -> frozenset[str]:
    """Words from campus place names. Location is a context signal, so it is not repeated in the description."""
    from app.geo.geofence import get_geofence

    terms: set[str] = set()
    for place in get_geofence().places:
        terms.update(tokenize(place.name))
    return frozenset(terms)


def description_terms(report) -> list[str]:
    """Identity terms of the free-text description.

    Removes words covered by other signals (category, colour, brand, model, feature cues, distinctive
    features), place names (context), and report boilerplate. Digits are dropped as time or number noise.
    """
    from app.ai.understanding import structured_terms

    excluded = (structured_terms() | location_terms() | BOILERPLATE
                | set(tokenize(report.distinctive_features or "")))
    return [t for t in tokenize(report.description or "") if t not in excluded and not t.isdigit()]
