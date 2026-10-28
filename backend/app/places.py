"""Download OpenStreetMap features and turn them into grounded place documents."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import PROJECT_ROOT


RAW_PATH = PROJECT_ROOT / "data" / "raw" / "karlsruhe_places.json"
CLEAN_PATH = PROJECT_ROOT / "data" / "places.json"
SNAPSHOT_METADATA_PATH = PROJECT_ROOT / "data" / "places_metadata.json"
OVERPASS_ENDPOINTS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
PHOTON_ENDPOINT = "https://photon.komoot.io/api/"
KARLSRUHE_BBOX = (48.86, 8.25, 49.13, 8.60)
# Very common geometry/access records swamp discovery queries without adding a
# distinct destination. Keep the compact, named places most useful for trips.
EXCLUDED_NOISE = {
    ("amenity", "bench"),
    ("natural", "scrub"),
    ("waterway", "stream"),
    ("highway", "footway"),
    ("highway", "track"),
}

# Keep categories broad enough for the assignment while retaining outdoor places
# from the starter application. These are all OSM tags, not generated facts.
TYPE_LABELS = {
    "amenity=restaurant": "Restaurant",
    "amenity=cafe": "Cafe",
    "amenity=fast_food": "Fast food restaurant",
    "amenity=food_court": "Food court",
    "amenity=ice_cream": "Ice cream shop",
    "amenity=school": "School",
    "amenity=college": "College",
    "amenity=university": "University",
    "amenity=kindergarten": "Kindergarten",
    "amenity=library": "Library",
    "amenity=hospital": "Hospital",
    "amenity=clinic": "Clinic",
    "amenity=doctors": "Doctor",
    "amenity=dentist": "Dentist",
    "amenity=pharmacy": "Pharmacy",
    "amenity=veterinary": "Veterinary clinic",
    "amenity=bus_station": "Bus station",
    "amenity=ferry_terminal": "Ferry terminal",
    "amenity=taxi": "Taxi stand",
    "amenity=bank": "Bank",
    "amenity=atm": "ATM",
    "amenity=post_office": "Post office",
    "amenity=toilets": "Public toilet",
    "amenity=community_centre": "Community centre",
    "amenity=place_of_worship": "Place of worship",
    "amenity=police": "Police station",
    "amenity=fire_station": "Fire station",
    "amenity=arts_centre": "Arts centre",
    "amenity=cinema": "Cinema",
    "amenity=theatre": "Theatre",
    "amenity=marketplace": "Marketplace",
    "amenity=fuel": "Fuel station",
    "amenity=charging_station": "EV charging station",
    "tourism=attraction": "Attraction",
    "tourism=museum": "Museum",
    "tourism=gallery": "Art gallery",
    "tourism=zoo": "Zoo",
    "tourism=aquarium": "Aquarium",
    "tourism=theme_park": "Theme park",
    "tourism=viewpoint": "Viewpoint",
    "tourism=hotel": "Hotel",
    "tourism=hostel": "Hostel",
    "tourism=guest_house": "Guest house",
    "tourism=camp_site": "Camp site",
    "tourism=information": "Visitor information point",
    "tourism=apartment": "Holiday apartment",
    "historic=castle": "Historic site",
    "historic=monument": "Historic monument",
    "historic=memorial": "Memorial",
    "historic=ruins": "Historic site",
    "shop=mall": "Shopping centre",
    "shop=department_store": "Department store",
    "shop=appliance": "Appliance shop",
    "shop=electronics": "Electronics shop",
    "shop=supermarket": "Supermarket",
    "shop=variety_store": "Variety store",
    "shop=books": "Book shop",
    "shop=clothes": "Clothing shop",
    "shop=convenience": "Convenience store",
    "shop=bakery": "Bakery",
    "shop=chemist": "Pharmacy",
    "shop=hardware": "Hardware shop",
    "shop=bicycle": "Bicycle shop",
    "shop=sports": "Sports shop",
    "shop=toys": "Toy shop",
    "shop=gift": "Gift shop",
    "shop=shoes": "Shoe shop",
    "shop=outdoor": "Outdoor equipment shop",
    "leisure=park": "Park",
    "leisure=fishing": "Fishing area",
    "leisure=nature_reserve": "Nature reserve",
    "leisure=picnic_table": "Picnic spot",
    "amenity=picnic_table": "Picnic spot",
    "amenity=bench": "Bench",
    "leisure=playground": "Playground",
    "leisure=garden": "Garden",
    "leisure=recreation_ground": "Recreation ground",
    "leisure=sports_centre": "Sports centre",
    "leisure=swimming_pool": "Swimming pool",
    "leisure=fitness_centre": "Fitness centre",
    "leisure=stadium": "Stadium",
    "leisure=pitch": "Sports pitch",
    "leisure=golf_course": "Golf course",
    "leisure=dog_park": "Dog park",
    "natural=water": "Water feature",
    "natural=wood": "Woodland",
    "natural=scrub": "Natural area",
    "landuse=forest": "Woodland",
    "water=lake": "Lake",
    "landuse=education": "Education campus",
    "building=school": "School",
    "building=college": "College",
    "building=university": "University",
    "building=kindergarten": "Kindergarten",
    "building=hospital": "Hospital",
    "office=educational_institution": "Education campus",
    "railway=station": "Train station",
    "railway=halt": "Railway halt",
    "railway=tram_stop": "Tram stop",
    "railway=subway_entrance": "Subway station",
    "highway=bus_stop": "Bus stop",
    "public_transport=platform": "Transit stop",
    "public_transport=station": "Transit station",
    "amenity=townhall": "Town hall",
    "highway=footway": "Footway",
    "highway=track": "Mapped track",
    "waterway=river": "River",
    "waterway=stream": "Stream",
    "waterway=canal": "Canal",
    "route=hiking": "Hiking route",
}

OVERPASS_QUERY = f"""[out:json][timeout:90];
(
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["amenity"~"^(restaurant|cafe|fast_food|food_court|ice_cream|picnic_table|bench|school|college|university|kindergarten|library|hospital|clinic|doctors|dentist|pharmacy|veterinary|bus_station|ferry_terminal|taxi|bank|atm|post_office|toilets|community_centre|place_of_worship|arts_centre|cinema|theatre|marketplace|fuel|charging_station|townhall|police|fire_station)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["building"~"^(school|college|university|kindergarten|hospital)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["landuse"="education"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["office"="educational_institution"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["tourism"~"^(attraction|museum|gallery|zoo|aquarium|theme_park|viewpoint|hotel|hostel|guest_house|camp_site|information|apartment)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["historic"~"^(castle|monument|memorial|ruins)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["shop"~"^(mall|department_store|appliance|electronics|supermarket|variety_store|books|clothes|convenience|bakery|chemist|hardware|bicycle|sports|toys|gift|shoes|outdoor)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["leisure"~"^(park|nature_reserve|picnic_table|playground|garden|recreation_ground|fishing|sports_centre|swimming_pool|fitness_centre|stadium|pitch|golf_course|dog_park)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["fishing"~"^(yes|permissive|private)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["natural"~"^(water|wood|scrub)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["waterway"~"^(river|stream|canal)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["railway"~"^(station|halt|tram_stop|subway_entrance)$"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["highway"="bus_stop"];
  nwr({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["public_transport"~"^(platform|station)$"];
  relation({KARLSRUHE_BBOX[0]},{KARLSRUHE_BBOX[1]},{KARLSRUHE_BBOX[2]},{KARLSRUHE_BBOX[3]})["route"="hiking"];
);
out center tags;"""

PHOTON_QUERIES = (
    "restaurants Karlsruhe", "cafes Karlsruhe", "attractions Karlsruhe",
    "museum Karlsruhe", "shopping centre Karlsruhe", "appliance shop Karlsruhe",
    "park Karlsruhe", "playground Karlsruhe", "school Karlsruhe", "university Karlsruhe",
    "library Karlsruhe", "hospital pharmacy clinic Karlsruhe", "train station bus stop Karlsruhe",
    "sports centre swimming pool Karlsruhe", "bank post office Karlsruhe", "hotel Karlsruhe",
    "fishing area Karlsruhe", "lake Karlsruhe",
)


def classify(tags: dict[str, Any]) -> str:
    # A single object can have several category tags. Prefer the specific
    # business/attraction category over a generic outdoor or land-use tag.
    if str(tags.get("fishing", "")).lower() in {"yes", "permissive", "private"}:
        return "Fishing area"
    for key in (
        "amenity", "shop", "tourism", "historic", "leisure", "natural", "landuse",
        "water", "highway", "waterway", "railway", "public_transport", "building",
        "office", "police", "fire_station", "route",
    ):
        value = tags.get(key)
        if value is not None:
            label = TYPE_LABELS.get(f"{key}={value}")
            if label:
                return label
    if tags.get("shop"):
        return "Shop"
    return "Place"


def coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    center = element.get("center") or {}
    lat = element.get("lat", center.get("lat"))
    lon = element.get("lon", center.get("lon"))
    if lat is None or lon is None:
        return None, None
    return float(lat), float(lon)


def describe(name: str, place_type: str, tags: dict[str, Any]) -> str:
    """Build searchable text using only values present in the OSM record."""
    details = [f"OSM category: {place_type}."]
    fields = (
        ("cuisine", "Cuisine"), ("brand", "Brand"), ("description", "Description"),
        ("operator", "Operator"), ("network", "Network"), ("capacity", "Capacity"),
        ("isced:level", "Education level"),
        ("historic", "Historic type"), ("wheelchair", "Wheelchair access"),
        ("opening_hours", "Opening hours"), ("fee", "Fee"), ("access", "Access"),
        ("outdoor_seating", "Outdoor seating"), ("website", "Website"),
        ("fishing", "Fishing access"),
    )
    for key, label in fields:
        value = tags.get(key)
        if key == "website":
            value = value or tags.get("contact:website")
        if value is not None and str(value).strip():
            details.append(f"{label}: {str(value).strip()}.")
    # Describe useful business/store categories in plain language so semantic
    # search can connect queries such as “washing machine” to an appliance shop.
    if tags.get("shop") == "appliance":
        details.append("Store category: household appliances.")
    elif tags.get("shop") == "electronics":
        details.append("Store category: consumer electronics.")
    text = " ".join(details)
    return f"{name} is an OpenStreetMap-listed {place_type.lower()} in the Karlsruhe search area, Germany. {text}"


def clean_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    for element in elements:
        tags = element.get("tags") or {}
        has_fishing_access = (
            tags.get("leisure") == "fishing"
            or str(tags.get("fishing", "")).lower() in {"yes", "permissive", "private"}
        )
        if not has_fishing_access and any((key, value) in EXCLUDED_NOISE for key, value in tags.items()):
            # A mapped footway or water feature may also carry a useful POI tag
            # such as amenity=school. Keep that destination and drop only pure
            # geometry/access noise.
            useful_poi = any(
                TYPE_LABELS.get(f"{key}={value}") not in {
                    None, "Bench", "Natural area", "Stream", "Footway", "Mapped track",
                }
                for key, value in tags.items()
            )
            if not useful_poi:
                continue
        lat, lon = coordinates(element)
        if lat is None or lon is None:
            continue
        # Ignore accidental neighbouring-town results if a provider returns a
        # feature outside the download area.
        if not (KARLSRUHE_BBOX[0] <= lat <= KARLSRUHE_BBOX[2] and KARLSRUHE_BBOX[1] <= lon <= KARLSRUHE_BBOX[3]):
            continue
        place_type = classify(tags)
        name = str(tags.get("name") or f"{place_type} (OSM {element.get('id')})").strip()
        osm_id = f"{element.get('type', 'object')}/{element.get('id')}"
        places.append({
            "id": osm_id,
            "name": name,
            "place_type": place_type,
            "lat": lat,
            "lon": lon,
            "description": describe(name, place_type, tags),
            "tags": tags,
        })
    # One named place may be returned by several category filters.
    unique: dict[str, dict[str, Any]] = {}
    for place in places:
        unique[place["id"]] = place
    return list(unique.values())


def load_local_osm(path: Path) -> tuple[int, int]:
    """Load an Overpass JSON export or an already-cleaned place JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("elements"), list):
        elements = payload["elements"]
        raw_payload = payload
    elif isinstance(payload, list) and payload and all(isinstance(item, dict) and "tags" in item for item in payload):
        elements = payload
        raw_payload = {"elements": elements, "source": "local OSM JSON"}
    elif isinstance(payload, list) and payload and all("description" in item and "id" in item for item in payload):
        places = payload
        elements = []
        raw_payload = {"source": "local cleaned JSON", "places": places}
    else:
        raise ValueError("Expected an Overpass JSON object with `elements` or a list of OSM place records.")

    if "places" not in raw_payload:
        places = clean_elements(elements)
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    CLEAN_PATH.write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_snapshot_metadata("local_import", "unknown", datetime.now(timezone.utc))
    return len(elements) or len(places), len(places)


def _write_snapshot_metadata(source: str, coverage: str, snapshot_updated_at: datetime) -> None:
    SNAPSHOT_METADATA_PATH.write_text(
        json.dumps({
            "source": source,
            "coverage": coverage,
            "snapshot_updated_at": snapshot_updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }, indent=2),
        encoding="utf-8",
    )


def _read_previous_snapshot() -> tuple[list[dict[str, Any]], datetime] | None:
    if not CLEAN_PATH.exists():
        return None
    places = json.loads(CLEAN_PATH.read_text(encoding="utf-8"))
    if not isinstance(places, list):
        return None
    try:
        metadata = json.loads(SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
        date_text = metadata.get("snapshot_updated_at")
        updated_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")) if date_text else None
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        updated_at = None
    if updated_at is None:
        updated_at = datetime.fromtimestamp(CLEAN_PATH.stat().st_mtime, tz=timezone.utc)
    elif updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return places, updated_at


def _fetch_overpass() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = httpx.post(
                endpoint,
                data={"data": OVERPASS_QUERY},
                timeout=httpx.Timeout(100.0, connect=10.0),
                headers={"User-Agent": "KarlsruheCityGuide/1.0 (learning project)"},
            )
            response.raise_for_status()
            raw = response.json()
            return raw, clean_elements(raw.get("elements", []))
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"Overpass servers failed: {last_error}")


def _fetch_photon() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    places: dict[str, dict[str, Any]] = {}
    features: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for query in PHOTON_QUERIES:
        try:
            response = httpx.get(
                PHOTON_ENDPOINT,
                params={"q": query, "limit": 25, "lat": 49.0069, "lon": 8.4037, "lang": "en"},
                timeout=httpx.Timeout(15.0, connect=8.0),
                headers={"User-Agent": "KarlsruheCityGuide/1.0 (learning project)"},
            )
            response.raise_for_status()
            result_features = response.json().get("features", [])
            features.extend(result_features)
            for feature in result_features:
                properties = feature.get("properties") or {}
                key, value = properties.get("osm_key"), properties.get("osm_value")
                if f"{key}={value}" not in TYPE_LABELS or not properties.get("osm_id"):
                    continue
                coordinates = (feature.get("geometry") or {}).get("coordinates") or []
                osm_type = {"N": "node", "W": "way", "R": "relation"}.get(properties.get("osm_type"))
                if len(coordinates) < 2 or not osm_type:
                    continue
                lon, lat = map(float, coordinates[:2])
                tags = {"name": properties.get("name") or "", key: value}
                for tag in ("street", "housenumber", "postcode", "city", "state", "country"):
                    if properties.get(tag):
                        tags[f"addr:{tag}"] = properties[tag]
                place = clean_elements([{
                    "type": osm_type,
                    "id": properties["osm_id"],
                    "lat": lat,
                    "lon": lon,
                    "tags": tags,
                }])
                if place:
                    places[place[0]["id"]] = place[0]
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
    if not places:
        raise RuntimeError(f"Photon fallback failed: {last_error}")
    return {"source": "Photon / OpenStreetMap", "features": features}, list(places.values())


def fetch_places() -> tuple[int, int]:
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    used_overpass = True
    try:
        raw, places = _fetch_overpass()
        source_count = len(raw.get("elements", []))
    except RuntimeError as overpass_error:
        used_overpass = False
        try:
            raw, places = _fetch_photon()
            source_count = len(raw.get("features", []))
        except RuntimeError as photon_error:
            raise RuntimeError(f"Could not fetch Karlsruhe data. {overpass_error} {photon_error}") from photon_error
    if not places:
        raise RuntimeError("The OSM query returned no supported, geolocated places.")

    fetched_at = datetime.now(timezone.utc)
    source = "overpass" if used_overpass else "photon_partial"
    coverage = "full" if used_overpass else "partial"
    if not used_overpass:
        previous = _read_previous_snapshot()
        if previous:
            previous_places, previous_updated_at = previous
            merged = {str(place.get("id")): place for place in previous_places if place.get("id")}
            merged.update({str(place.get("id")): place for place in places if place.get("id")})
            places = list(merged.values())
            source = "photon_partial_merge"
            # A partial lookup must not erase existing places or make older
            # records appear newly fetched.
            fetched_at = previous_updated_at

    RAW_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    CLEAN_PATH.write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_snapshot_metadata(source, coverage, fetched_at)
    return source_count, len(places)
