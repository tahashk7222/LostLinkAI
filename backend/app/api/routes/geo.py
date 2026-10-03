from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.geo.geofence import (EDGE_TOLERANCE_M, OUT_OF_AREA_MESSAGE, classify, describe, get_geofence,
                              nearest_place)

router = APIRouter(prefix="/geo", tags=["location"])


@router.get("/config")
def geofence_config(_: CurrentUser):
    """The permitted area and quick-select places (single source of truth for the frontend)."""
    f = get_geofence()
    return {
        "id": f.id,
        "name": f.name,
        "zones": f.zones,
        "nearby_buffer_m": f.nearby_buffer_m,
        "edge_tolerance_m": EDGE_TOLERANCE_M,
        "campus_polygon": [list(p) for p in f.polygon],
        "places": [{"key": p.key, "name": p.name, "lat": p.lat, "lng": p.lng, "area": p.area} for p in f.places],
        "attribution": f.attribution,
        "out_of_area_message": OUT_OF_AREA_MESSAGE,
    }


@router.get("/resolve")
def resolve_point(_: CurrentUser, lat: Annotated[float, Query(ge=-90, le=90)],
                  lng: Annotated[float, Query(ge=-180, le=180)]):
    """Check a point against the geofence and suggest a readable label. Nothing is stored."""
    zone = classify(lat, lng)
    if zone is None:
        return {"allowed": False, "zone": None, "message": OUT_OF_AREA_MESSAGE}
    near = nearest_place(lat, lng)
    return {"allowed": True, "zone": zone, "label": describe(lat, lng),
            "nearest_place": near[0].name if near else None,
            "nearest_distance_m": round(near[1]) if near else None}
