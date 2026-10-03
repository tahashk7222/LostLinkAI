"""Explicit identifiers (serials, initials, quoted names) in typed features: conflicts are contradictions (scoring v3).

Only the v3 scorer checks identifiers. v2 keeps its recorded behaviour.
"""

import dataclasses

from app.ai.config import get_matching_config
from tests.test_ai_units import report
from tests.test_scoring_v3 import _same_spot, _score

cfg = get_matching_config()
v2 = dataclasses.replace(cfg, scorer="v2")


def _feature_pair(lost_text, found_text):
    lost = report(category="Phone", name="Phone", color="black", description="black phone", distinctive_features=lost_text,
                  **_same_spot())
    found = report(category="Phone", name="Phone", color="black", description="black phone",
                   distinctive_features=found_text, **_same_spot())
    return lost, found


def _identifier_conflicts(res):
    return [e for e in res.evidence if e["direction"] == "contradicts" and "identifiers" in e["text"]]


# 1. same serial -> match
def test_same_serial_is_a_match():
    lost, found = _feature_pair("label with serial 4821 under the back cover",
                                "label with serial 4821 under the back cover")
    res = _score(lost, found)
    assert res.signals["features"] >= 0.5
    assert "features" in res.identity_groups
    assert _identifier_conflicts(res) == []


# 2. different serial -> contradiction
def test_different_serial_is_a_contradiction_not_a_match():
    lost, found = _feature_pair("label with serial 4821 under the back cover",
                                "label with serial 9075 under the back cover")
    res = _score(lost, found)
    assert _identifier_conflicts(res)
    assert "features" not in res.identity_groups
    assert res.score <= 0.45
    assert res.lead not in ("STRONG", "POSSIBLE") and res.notify_eligible is False


# 3. same initials -> match
def test_same_initials_is_a_match():
    lost, found = _feature_pair("initials AK inside the front pocket", "initials AK inside the front pocket")
    res = _score(lost, found)
    assert "features" in res.identity_groups
    assert _identifier_conflicts(res) == []


# 4. different initials -> contradiction
def test_different_initials_is_a_contradiction():
    lost, found = _feature_pair("initials AK inside the front pocket", "initials MR inside the front pocket")
    res = _score(lost, found)
    assert _identifier_conflicts(res)
    assert "features" not in res.identity_groups
    assert res.notify_eligible is False


# 5. same explicit name -> match
def test_same_quoted_name_is_a_match():
    lost, found = _feature_pair("engraved 'AYESHA 2019' on the back cover", "engraved 'AYESHA 2019' on the back cover")
    res = _score(lost, found)
    assert "features" in res.identity_groups
    assert _identifier_conflicts(res) == []


# 6. different explicit name -> contradiction
def test_different_quoted_name_is_a_contradiction():
    lost, found = _feature_pair("engraved 'AYESHA 2019' on the back cover", "engraved 'BILAL 2018' on the back cover")
    res = _score(lost, found)
    assert _identifier_conflicts(res)
    assert "features" not in res.identity_groups
    assert res.notify_eligible is False


# 7. no identifiers -> normal similarity behaviour
def test_feature_text_without_identifiers_uses_normal_similarity():
    lost, found = _feature_pair("cricket team sticker on the front pocket", "cricket team sticker on the front pocket")
    res = _score(lost, found)
    assert res.signals["features"] >= 0.5
    assert _identifier_conflicts(res) == []


def test_partial_wording_without_identifiers_is_not_a_conflict():
    lost, found = _feature_pair("torn left strap", "torn strap")
    res = _score(lost, found)
    assert _identifier_conflicts(res) == []


def test_one_side_stating_fewer_identifiers_is_not_a_contradiction():
    """One report names the owner and the year, the other only the year. Nothing conflicts."""
    lost, found = _feature_pair("engraved 'AYESHA 2019' on the back cover", "engraved 2019 on the back cover")
    res = _score(lost, found)
    assert _identifier_conflicts(res) == []


def test_same_name_different_year_is_a_contradiction():
    lost, found = _feature_pair("engraved 'AYESHA 2019' on the back cover", "engraved 'AYESHA 2018' on the back cover")
    res = _score(lost, found)
    assert _identifier_conflicts(res)
    assert "features" not in res.identity_groups


def test_identifier_check_is_v3_only_so_v2_history_reproduces():
    lost, found = _feature_pair("label with serial 4821 under the back cover",
                                "label with serial 9075 under the back cover")
    res = _score(lost, found, config=v2)
    assert not _identifier_conflicts(res)  # v2 keeps its recorded behaviour
    assert res.signals["features"] > 0


def test_cases_set_serial_false_positive_no_longer_notifies():
    """The reported bug as a pair: a serial mismatch must not notify, under the default (v3) scorer."""
    lost, found = _feature_pair("label with serial 4821 under the back cover",
                                "label with serial 9075 under the back cover")
    res = _score(lost, found)
    assert res.notify_eligible is False
