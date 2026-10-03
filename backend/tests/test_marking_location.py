"""Marking or damage identity needs a close location to notify (scoring v3).

"Close" means the same place, or at most NEAR_M (250 m) apart. The distance is the existing geofence distance.
The relevance score still reflects location through the normal location signal; only the lead and notification change.
"""

from app.ai.config import get_matching_config
from tests.test_ai_units import report
from tests.test_scoring_v3 import _score

NEAR_LAT, NEAR_LNG = 31.5788, 74.3567  # the reference point
NEAR_DEG = 0.001  # about 110 m north
FAR_DEG = 0.02  # about 2.2 km north
cfg = get_matching_config()


def _pair(*, found_lat=NEAR_LAT, found_lng=NEAR_LNG, lost_place=None, found_place=None, lost_feature, found_feature,
          lost_desc=None, found_desc=None):
    lost = report(category="Phone", name="Phone", color="black", description=lost_desc or "black phone",
                  distinctive_features=lost_feature, date_time=_when(), location="Lecture Theatre",
                  latitude=NEAR_LAT, longitude=NEAR_LNG, place_key=lost_place)
    found = report(category="Phone", name="Phone", color="black", description=found_desc or "black phone",
                   distinctive_features=found_feature, date_time=_when(), location="Lecture Theatre",
                   latitude=found_lat, longitude=found_lng, place_key=found_place)
    return lost, found


def _when():
    from datetime import datetime, timezone
    return datetime(2026, 10, 1, 15, tzinfo=timezone.utc)


MARKING = "initials AK inside the front pocket"


def test_marking_only_far_apart_does_not_notify():
    lost, found = _pair(found_lat=NEAR_LAT + FAR_DEG, lost_feature=MARKING, found_feature=MARKING)
    res = _score(lost, found)
    assert res.identity_groups == ["features"]  # the identity is still recorded
    assert res.lead == "WEAK"
    assert res.notify_eligible is False


def test_marking_only_close_notifies():
    lost, found = _pair(found_lat=NEAR_LAT + NEAR_DEG, lost_feature=MARKING, found_feature=MARKING)
    res = _score(lost, found)
    assert res.lead in ("STRONG", "POSSIBLE")
    assert res.notify_eligible is True


def test_same_place_key_is_close_even_with_distant_coordinates():
    lost, found = _pair(found_lat=NEAR_LAT + FAR_DEG, lost_place="lecture-theatre", found_place="lecture-theatre",
                        lost_feature=MARKING, found_feature=MARKING)
    res = _score(lost, found)
    assert res.lead in ("STRONG", "POSSIBLE")
    assert res.notify_eligible is True


def test_marking_far_apart_still_keeps_its_relevance_score_and_weak_lead():
    near_lost, near_found = _pair(found_lat=NEAR_LAT + NEAR_DEG, lost_feature=MARKING, found_feature=MARKING)
    far_lost, far_found = _pair(found_lat=NEAR_LAT + FAR_DEG, lost_feature=MARKING, found_feature=MARKING)
    near, far = _score(near_lost, near_found), _score(far_lost, far_found)
    assert far.score > 0  # relevance is kept, so the candidate remains visible
    assert far.score < near.score  # the general location signal still lowers relevance with distance
    assert far.lead == "WEAK" and near.lead in ("STRONG", "POSSIBLE")


def test_model_identity_far_apart_is_not_blocked_by_distance():
    """Only marking or damage identity is limited by distance. A shared model code is not."""
    lost, found = _pair(found_lat=NEAR_LAT + FAR_DEG, lost_feature=None, found_feature=None,
                        lost_desc="black Casio F-91W watch", found_desc="black Casio F-91W watch")
    res = _score(lost, found)
    assert "model" in res.identity_groups
    assert res.notify_eligible == (res.lead in ("STRONG", "POSSIBLE"))
    if res.score >= cfg.threshold:
        assert res.lead in ("STRONG", "POSSIBLE")


def test_missing_coordinates_count_as_not_close():
    lost, found = _pair(found_lat=None, lost_feature=MARKING, found_feature=MARKING)
    res = _score(lost, found)
    assert res.notify_eligible is False
