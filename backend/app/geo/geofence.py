"""Geographic scope of LostLink AI (UET Lahore).

The boundary lives in a JSON file (default: app/geo/uet_lahore.json, override with
GEOFENCE_FILE) so it can be changed without touching code:

- campus_polygon: [[lat, lng], ...] — the campus outline (from OpenStreetMap)
- nearby_buffer_m: points within this distance outside the campus are "nearby"
- places: quick-select locations with sourced coordinates

This module is the authoritative check; the frontend mirrors it only for UX.
"""

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

CAMPUS = "campus"
NEARBY = "nearby"
OUT_OF_AREA_MESSAGE = "LostLink is currently limited to UET Lahore and its nearby area."

_EARTH_M = 6371000.0
# Points this close to the campus outline (gates sit on the wall) count as campus.
EDGE_TOLERANCE_M = 15.0
# "Near" a place: used for the display label and as the close-location limit for matching.
NEAR_M = 250.0


@dataclass(frozen=True)
class Place:
    key: str
    name: str
    lat: float
    lng: float
    area: str
    source: str


@dataclass(frozen=True)
class Geofence:
    id: str
    name: str
    zones: dict
    nearby_buffer_m: float
    polygon: tuple[tuple[float, float], ...]
    places: tuple[Place, ...]
    attribution: str
    raw: dict

    def place(self, key: str) -> Place | None:
        return next((p for p in self.places if p.key == key), None)


@lru_cache
def get_geofence() -> Geofence:
    path = get_settings().geofence_file or str(Path(__file__).with_name("uet_lahore.json"))
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    polygon = tuple((float(a), float(b)) for a, b in raw["campus_polygon"])
    if len(polygon) < 3:
        raise ValueError("Geofence polygon needs at least 3 points")
    places = tuple(Place(p["key"], p["name"], float(p["lat"]), float(p["lng"]), p.get("area", ""),
                         p.get("source", "")) for p in raw.get("places", []))
    return Geofence(raw["id"], raw["name"], raw.get("zones", {}), float(raw.get("nearby_buffer_m", 0)),
                    polygon, places, raw.get("attribution", ""), raw)


def _to_xy(lat: float, lng: float, lat0: float) -> tuple[float, float]:
    """Local equirectangular projection in metres (accurate at campus scale)."""
    x = math.radians(lng) * _EARTH_M * math.cos(math.radians(lat0))
    y = math.radians(lat) * _EARTH_M
    return x, y


def point_in_polygon(lat: float, lng: float, polygon) -> bool:
    """Ray casting; polygon is a sequence of (lat, lng)."""
    inside = False
    n = len(polygon)
    for i in range(n):
        y1, x1 = polygon[i]
        y2, x2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lng < x_cross:
                inside = not inside
    return inside


def distance_to_polygon_m(lat: float, lng: float, polygon) -> float:
    """Distance from a point to the polygon boundary in metres (0 if on the edge)."""
    lat0 = polygon[0][0]
    px, py = _to_xy(lat, lng, lat0)
    best = float("inf")
    n = len(polygon)
    for i in range(n):
        ax, ay = _to_xy(*polygon[i], lat0)
        bx, by = _to_xy(*polygon[(i + 1) % n], lat0)
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(a))


def classify(lat: float, lng: float, fence: Geofence | None = None) -> str | None:
    """Return 'campus', 'nearby' or None (outside the permitted area)."""
    fence = fence or get_geofence()
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if point_in_polygon(lat, lng, fence.polygon):
        return CAMPUS
    edge = distance_to_polygon_m(lat, lng, fence.polygon)
    if edge <= EDGE_TOLERANCE_M:
        return CAMPUS
    if edge <= fence.nearby_buffer_m:
        return NEARBY
    return None


def nearest_place(lat: float, lng: float, fence: Geofence | None = None) -> tuple[Place, float] | None:
    fence = fence or get_geofence()
    if not fence.places:
        return None
    return min(((p, distance_m(lat, lng, p.lat, p.lng)) for p in fence.places), key=lambda t: t[1])


def area_of(lat: float | None, lng: float | None, place_key: str | None = None,
            fence: Geofence | None = None, radius_m: float = 150) -> str | None:
    """Logical campus area of a location (e.g. 'sports'), from its place or the nearest place."""
    fence = fence or get_geofence()
    if place_key and (p := fence.place(place_key)):
        return p.area or None
    if lat is None or lng is None:
        return None
    near = nearest_place(lat, lng, fence)
    if near is None or near[1] > radius_m:
        return None
    return near[0].area or None


def describe(lat: float, lng: float, fence: Geofence | None = None) -> str:
    """Human-readable label for a point, e.g. 'Near Lecture Theatre'. Never exposes coordinates."""
    fence = fence or get_geofence()
    near = nearest_place(lat, lng, fence)
    zone = classify(lat, lng, fence)
    if near and near[1] <= NEAR_M:
        return f"Near {near[0].name}"
    return fence.zones.get(zone, fence.name) if zone else fence.name
