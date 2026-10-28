"""Geocode a Karlsruhe starting point and order recommended stops by distance."""

import math
import logging
import re
from typing import Any

import httpx

from .places import KARLSRUHE_BBOX, PHOTON_ENDPOINT
from .config import settings


DEFAULT_ORIGIN = (49.0069, 8.4037)  # Karlsruhe city centre
NEARBY_SHORTLIST_RADIUS_KM = 5.0
COORDINATE_PATTERN = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")
logger = logging.getLogger(__name__)


def haversine_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Return great-circle distance; this is an estimate, not road distance."""
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def resolve_origin(value: str | None) -> dict[str, Any]:
    """Accept coordinates or resolve a Karlsruhe place name with Photon."""
    if not value or not value.strip():
        return {
            "label": "Karlsruhe city centre (default)",
            "lat": DEFAULT_ORIGIN[0],
            "lon": DEFAULT_ORIGIN[1],
            "source": "default",
        }

    raw = value.strip()
    coordinate_match = COORDINATE_PATTERN.match(raw)
    if coordinate_match:
        lat, lon = map(float, coordinate_match.groups())
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Coordinates must be latitude, longitude within valid ranges.")
        if not (KARLSRUHE_BBOX[0] <= lat <= KARLSRUHE_BBOX[2] and KARLSRUHE_BBOX[1] <= lon <= KARLSRUHE_BBOX[3]):
            raise ValueError("Starting point is outside the Karlsruhe search area.")
        return {"label": raw, "lat": lat, "lon": lon, "source": "coordinates"}

    try:
        response = httpx.get(
            PHOTON_ENDPOINT,
            params={"q": f"{raw}, Karlsruhe, Germany", "limit": 5, "lat": DEFAULT_ORIGIN[0], "lon": DEFAULT_ORIGIN[1]},
            timeout=httpx.Timeout(8.0, connect=4.0),
            headers={"User-Agent": "KarlsruheCityGuide/1.0 (learning project)"},
        )
        response.raise_for_status()
        features = response.json().get("features", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("Could not look up that starting point. Enter Karlsruhe coordinates such as 49.0093, 8.4020.") from exc

    for feature in features:
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        lon, lat = map(float, coordinates[:2])
        if KARLSRUHE_BBOX[0] <= lat <= KARLSRUHE_BBOX[2] and KARLSRUHE_BBOX[1] <= lon <= KARLSRUHE_BBOX[3]:
            properties = feature.get("properties") or {}
            name = properties.get("name") or raw
            return {"label": f"{name}, Karlsruhe", "lat": lat, "lon": lon, "source": "OpenStreetMap/Photon"}
    raise ValueError("Starting point was not found in the Karlsruhe area. Try another name or enter coordinates.")


def _walking_trip(
    origin: dict[str, Any], places: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, float]], list[list[float]], float, float] | None:
    """Ask the OSM foot router for a walking path and its leg distances."""
    points = [(float(origin["lat"]), float(origin["lon"]))]
    points.extend((float(place["lat"]), float(place["lon"])) for place in places)
    encoded_points = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    is_trip = len(points) > 2
    service = "trip" if is_trip else "route"
    endpoint = f"{settings.walking_router_url.rstrip('/')}/{service}/v1/driving/{encoded_points}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    if is_trip:
        params.update({"roundtrip": "false", "source": "first", "destination": "last"})

    try:
        response = httpx.get(
            endpoint,
            params=params,
            timeout=httpx.Timeout(settings.walking_router_timeout_seconds, connect=3.0),
            headers={"User-Agent": "KarlsruheCityCompass/1.0 (local place-search learning project)"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "Ok":
            return None
        route_key = "trips" if is_trip else "routes"
        routes = payload.get(route_key) or []
        if not routes:
            return None
        route = routes[0]
        legs = route.get("legs") or []
        geometry = (route.get("geometry") or {}).get("coordinates") or []
        if len(legs) != len(places) or len(geometry) < 2:
            return None

        if is_trip:
            waypoints = payload.get("waypoints") or []
            if len(waypoints) != len(points):
                return None
            input_by_route_order: dict[int, int] = {}
            for input_index, waypoint in enumerate(waypoints):
                route_order = waypoint.get("waypoint_index")
                if not isinstance(route_order, int) or route_order in input_by_route_order:
                    return None
                input_by_route_order[route_order] = input_index
            if set(input_by_route_order) != set(range(len(points))) or input_by_route_order.get(0) != 0:
                return None
            # Waypoint indexes include the origin at input index 0; the place
            # list starts at input index 1.
            ordered_places = [places[input_by_route_order[index] - 1] for index in range(1, len(points))]
        else:
            ordered_places = places[:]

        if any(not isinstance(leg.get("distance"), (int, float)) or not isinstance(leg.get("duration"), (int, float)) for leg in legs):
            return None
        path = [[float(lat), float(lon)] for lon, lat in geometry]
        return (
            ordered_places,
            [{"distance_km": float(leg["distance"]) / 1000, "duration_minutes": float(leg["duration"]) / 60} for leg in legs],
            path,
            float(route.get("distance", sum(leg["distance"] for leg in legs))) / 1000,
            float(route.get("duration", sum(leg["duration"] for leg in legs))) / 60,
        )
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        logger.info("OpenStreetMap foot routing unavailable (%s)", type(exc).__name__)
        return None


def plan_route(
    places: list[dict[str, Any]], origin_text: str | None, limit: int = 5
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select relevant nearby matches and suggest a visit order.

    Retrieval similarity stays visible as `score`. A separate relevance-plus-
    proximity value chooses the shortlist. The OpenStreetMap foot router then
    orders and routes selected stops where available; otherwise the response
    clearly identifies its straight-line estimate fallback.
    """
    origin = resolve_origin(origin_text)
    if not places:
        return [], {
            "origin": origin,
            "distance_km": 0.0,
            "duration_minutes": None,
            "geometry": [[origin["lat"], origin["lon"]]],
            "mode": "no-stops",
            "disclaimer": "No matching places were found.",
        }

    candidates = []
    for place in places:
        point = (float(place["lat"]), float(place["lon"]))
        from_origin = haversine_km((origin["lat"], origin["lon"]), point)
        proximity = math.exp(-from_origin / 5.0)
        # Category intent is already a hard Milvus filter. For nearby discovery,
        # give location enough weight to keep a semantically similar venue across
        # town from displacing a genuinely nearby match.
        rank = 0.55 * float(place.get("score") or 0) + 0.45 * proximity
        candidates.append({**place, "distance_km": round(from_origin, 2), "_route_rank": rank})
    within_nearby_radius = [item for item in candidates if item["distance_km"] <= NEARBY_SHORTLIST_RADIUS_KM]
    if len(within_nearby_radius) >= limit:
        candidates = within_nearby_radius
    candidates.sort(key=lambda item: (item["_route_rank"], item["score"]), reverse=True)
    selected = candidates[:limit]

    ordered: list[dict[str, Any]] = []
    remaining = selected[:]
    current = (origin["lat"], origin["lon"])
    geometry = [[origin["lat"], origin["lon"]]]
    total_distance = 0.0
    while remaining:
        def next_score(place: dict[str, Any]) -> tuple[float, float]:
            leg = haversine_km(current, (place["lat"], place["lon"]))
            locality = math.exp(-leg / 3.0)
            return (0.78 * locality + 0.22 * place["_route_rank"], place["score"])

        chosen = max(remaining, key=next_score)
        remaining.remove(chosen)
        point = (chosen["lat"], chosen["lon"])
        leg_distance = haversine_km(current, point)
        total_distance += leg_distance
        chosen["route_order"] = len(ordered) + 1
        chosen["leg_distance_km"] = round(leg_distance, 2)
        chosen.pop("_route_rank", None)
        ordered.append(chosen)
        geometry.append([chosen["lat"], chosen["lon"]])
        current = point

    walking = _walking_trip(origin, ordered)
    if walking:
        walked_places, legs, walking_geometry, walking_distance, walking_duration = walking
        for index, place in enumerate(walked_places):
            place["route_order"] = index + 1
            place["leg_distance_km"] = round(legs[index]["distance_km"], 2)
            place["leg_duration_minutes"] = round(legs[index]["duration_minutes"], 1)
        return walked_places, {
            "origin": origin,
            "distance_km": round(walking_distance, 2),
            "duration_minutes": round(walking_duration, 1),
            "geometry": walking_geometry,
            "mode": "walking",
            "source": "OpenStreetMap foot router",
            "disclaimer": "Estimated walking route on mapped paths and streets. Temporary closures, private access, and on-site conditions may differ.",
        }

    return ordered, {
        "origin": origin,
        "distance_km": round(total_distance, 2),
        "duration_minutes": None,
        "geometry": geometry,
        "mode": "straight-line-estimate",
        "source": "OpenStreetMap coordinates",
        "disclaimer": "The walking router did not return a route. Distances and map lines are straight-line estimates, not walking directions.",
    }
