"""A reported colour conflict blocks notification unless strong identity is present (scoring v3).

Strong identity here is a shared model code or an identifier-matched feature. Generic markings, brand and
accessories do not count. The relevance score is not changed by the colour rule.
"""

from tests.test_ai_units import report
from tests.test_scoring_v3 import _same_spot, _score


def _pair(lost_colour, found_colour, *, lost_feature=None, found_feature=None, lost_desc=None, found_desc=None,
          lost_brand=None, found_brand=None):
    lost = report(category="Phone", name="Phone", color=lost_colour, brand=lost_brand,
                  description=lost_desc or f"{lost_colour} phone", distinctive_features=lost_feature, **_same_spot())
    found = report(category="Phone", name="Phone", color=found_colour, brand=found_brand,
                   description=found_desc or f"{found_colour} phone", distinctive_features=found_feature,
                   **_same_spot())
    return lost, found


# 1. same colour: colour does not block a matching identity
def test_same_colour_with_strong_identity_notifies():
    lost, found = _pair("black", "black", lost_feature="initials AK inside the front pocket",
                        found_feature="initials AK inside the front pocket")
    res = _score(lost, found)
    assert res.lead in ("STRONG", "POSSIBLE")
    assert res.notify_eligible is True


# 2. compatible colour family: not a conflict
def test_compatible_colour_family_is_not_a_conflict():
    lost, found = _pair("navy blue", "blue", lost_feature="initials AK inside the front pocket",
                        found_feature="initials AK inside the front pocket")
    res = _score(lost, found)
    assert res.signals["color"] >= 0.5
    assert "color" not in res.caps
    assert res.notify_eligible is True


# 3. conflicting colours with weak, generic evidence: no notification
def test_conflicting_colours_with_generic_evidence_do_not_notify():
    lost, found = _pair("silver", "blue", lost_feature="cricket team sticker on the front pocket",
                        found_feature="cricket team sticker on the front pocket")
    res = _score(lost, found)
    assert "color" in res.caps  # the colour conflict was recorded
    assert res.notify_eligible is False
    assert res.lead in (None, "WEAK")


# 4. conflicting colours with strong identity: the candidate stays relevant
def test_conflicting_colours_with_model_identity_stay_relevant():
    lost, found = _pair("silver", "blue", lost_desc="silver Casio F-91W watch", found_desc="blue Casio F-91W watch")
    res = _score(lost, found)
    assert "color" in res.caps
    assert "model" in res.identity_groups
    assert res.lead is not None  # kept as a lead, not rejected
    assert res.notify_eligible == (res.lead in ("STRONG", "POSSIBLE"))
