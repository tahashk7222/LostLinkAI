"""A feature phrase takes the type of its most identifying cue (marking and damage over accessory and other)."""

from app.ai.understanding import extract_typed_features


def _kinds(text: str) -> dict[str, str]:
    return {f.phrase: f.kind for f in extract_typed_features(text)}


def test_marking_beats_accessory_in_the_same_phrase():
    assert _kinds("engraved back cover")["engraved back cover"] == "marking"


def test_damage_beats_accessory_in_the_same_phrase():
    kinds = _kinds("torn left strap and a leather strap with a scratch")
    assert kinds["torn left strap"] == "damage"
    assert kinds["a leather strap with a scratch"] == "damage"


def test_plain_accessory_stays_accessory():
    assert _kinds("football shaped keychain")["football shaped keychain"] == "accessory"
