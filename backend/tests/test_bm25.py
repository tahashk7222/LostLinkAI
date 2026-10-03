"""BM25 lexical similarity: IDF weighting, normalisation, and structured-word exclusion."""

from types import SimpleNamespace

from app.ai.lexical import BM25Index, description_terms
from app.ai.providers.text import tokenize


def test_rare_identifying_term_outweighs_generic_overlap():
    docs = [tokenize("black bag with a bag strap"), tokenize("calculus notebook in a bag"),
            tokenize("plain bag"), tokenize("black bag"), tokenize("silver bag")]
    index = BM25Index(docs)
    query = tokenize("bag with calculus notebook")
    rare = index.normalized(query, tokenize("calculus notebook in a bag"))
    generic = index.normalized(query, tokenize("black bag with a bag strap"))
    assert rare > generic


def test_scores_are_bounded_and_identical_text_scores_highest():
    docs = [tokenize("red wallet with photo of a child"), tokenize("green water bottle"), tokenize("ID card")]
    index = BM25Index(docs)
    q = docs[0]
    assert index.normalized(q, q) == 1.0
    for d in docs:
        assert 0.0 <= index.normalized(q, d) <= 1.0
    assert index.normalized(q, docs[1]) == 0.0  # no shared terms


def test_empty_inputs_score_zero():
    index = BM25Index([tokenize("a bag")])
    assert index.normalized([], tokenize("a bag")) == 0.0
    assert index.normalized(tokenize("bag"), []) == 0.0


def test_structured_words_are_excluded_from_description_terms():
    r = SimpleNamespace(description="Lost my black Jansport backpack with calculus notes near the library",
                        distinctive_features="red keychain")
    terms = description_terms(r)
    assert "black" not in terms and "jansport" not in terms and "backpack" not in terms
    assert tokenize("calculus")[0] in terms and "library" in terms
    assert "keychain" not in terms and "red" not in terms  # feature words are scored by the features signal
