"""Authoritative location resolution for reports (never trusts client-side geofence checks).

A report location must be one of:
- predefined: a known place key -> server uses that place's coordinates
- gps / map:  a point that must lie inside the UET Lahore campus or its nearby area

Free text alone is not accepted: it cannot be checked against the geofence. The text is
kept as the human-readable label (e.g. "Near Gate 3, bus stop").
The zone is always computed here, from the coordinates.
"""

from dataclasses import dataclass

from app.core.errors import AppError
from app.geo.geofence import OUT_OF_AREA_MESSAGE, classify, describe, get_geofence

POINT_TYPES = ("gps", "map")


@dataclass
class ResolvedLocation:
    location: str
    latitude: float
    longitude: float
    zone: str
    location_type: str
    place_key: str | None

    def as_fields(self) -> dict:
        return {"location": self.location, "latitude": self.latitude, "longitude": self.longitude,
                "zone": self.zone, "location_type": self.location_type, "place_key": self.place_key}


def resolve_location(text: str | None, place_key: str | None, latitude: float | None, longitude: float | None,
                     location_type: str | None) -> ResolvedLocation:
    fence = get_geofence()
    text = (text or "").strip() or None

    if place_key:
        place = fence.place(place_key)
        if place is None:
            raise AppError(422, "Unknown UET location. Please choose one from the list.")
        zone = classify(place.lat, place.lng, fence)
        if zone is None:  # misconfigured place outside the boundary
            raise AppError(422, OUT_OF_AREA_MESSAGE)
        return ResolvedLocation(text or place.name, place.lat, place.lng, zone, "predefined", place.key)

    if latitude is None or longitude is None:
        raise AppError(422, "Please choose a UET Lahore location, use your location, or pick a spot on the map.")
    zone = classify(latitude, longitude, fence)
    if zone is None:
        raise AppError(422, OUT_OF_AREA_MESSAGE)
    kind = location_type if location_type in POINT_TYPES else "map"
    return ResolvedLocation(text or describe(latitude, longitude, fence), latitude, longitude, zone, kind, None)
