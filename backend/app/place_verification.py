"""Live, bounded OpenStreetMap verification with candidate refill."""

import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from .place_categories import PLACE_TYPES_BY_CATEGORY
from .places import CLEAN_PATH, SNAPSHOT_METADATA_PATH, OVERPASS_ENDPOINTS, classify, coordinates, describe


CHECK_BATCH_SIZE = 5
MAX_OSM_CHECKS = 20
OSM_ID_PATTERN = re.compile(r"^(node|way|relation)/(\d+)$")
OVERPASS_TYPES = {"node": "node", "way": "way", "relation": "rel"}
USER_AGENT = "KarlsruheCityCompass/1.0 (local place-search learning project)"
ENDPOINT_TIMEOUT_SECONDS = 6.0
SNAPSHOT_MAX_AGE_DAYS = 14
logger = logging.getLogger(__name__)


class OSMVerificationUnavailable(Exception):
    """All configured Overpass endpoints failed this verification request."""


def _osm_lifecycle_closed(tags: dict[str, Any]) -> bool:
    closed_values = {"yes", "true", "permanently", "closed"}
    if any(
        str(tags.get(key, "")).strip().casefold() in closed_values
        for key in ("closed", "disused", "abandoned", "demolished", "razed")
    ):
        return True
    if any(
        key.startswith("closed:") and str(value).strip().casefold() in closed_values
        for key, value in tags.items()
    ):
        return True
    if str(tags.get("status", "")).strip().casefold() in {"closed", "permanently closed"}:
        return True
    lifecycle_prefixes = ("disused:", "abandoned:", "demolished:", "razed:", "was:")
    place_keys = {"amenity", "shop", "tourism", "leisure", "historic", "natural", "water", "waterway"}
    return any(
        key.startswith(lifecycle_prefixes) and key.split(":", 1)[1] in place_keys
        for key in tags
    )


def _overpass_query(candidates: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    by_kind: dict[str, list[str]] = defaultdict(list)
    indexed: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        osm_id = str(candidate.get("id", ""))
        match = OSM_ID_PATTERN.fullmatch(osm_id)
        if not match:
            continue
        osm_type, numeric_id = match.groups()
        by_kind[osm_type].append(numeric_id)
        indexed[osm_id] = candidate

    statements = []
    for osm_type, ids in by_kind.items():
        unique_ids = ",".join(dict.fromkeys(ids))
        statements.append(f"{OVERPASS_TYPES[osm_type]}(id:{unique_ids});")
    query = "[out:json][timeout:20];(" + "".join(statements) + ");out center tags;"
    return query, indexed


async def _fetch_live_batch(
    client: httpx.AsyncClient,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    query, indexed = _overpass_query(candidates)
    if not indexed:
        return {}

    errors: list[str] = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = await asyncio.wait_for(
                client.post(endpoint, data={"data": query}),
                timeout=ENDPOINT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Overpass response was not a JSON object")
            elements = payload.get("elements")
            if not isinstance(elements, list):
                raise ValueError("Overpass response did not contain an elements list")
            return {
                f"{element.get('type')}/{element.get('id')}": element
                for element in elements
                if isinstance(element, dict)
            }
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError) as exc:
            host = urlparse(endpoint).hostname or "OpenStreetMap"
            logger.warning("Overpass verification failed at %s (%s)", host, type(exc).__name__)
            errors.append(type(exc).__name__)
    raise OSMVerificationUnavailable("; ".join(errors))


def _refresh_from_live_osm(
    candidate: dict[str, Any],
    element: dict[str, Any],
    expected_categories: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    tags = element.get("tags") or {}
    if _osm_lifecycle_closed(tags):
        return None, "closed"

    live_type = classify(tags)
    allowed_types = {
        place_type
        for category in expected_categories
        for place_type in PLACE_TYPES_BY_CATEGORY.get(category, ())
    }
    if expected_categories and live_type not in allowed_types:
        return None, "mismatch"
    if not expected_categories and live_type != str(candidate.get("place_type", "Place")):
        return None, "mismatch"
    if live_type == "Place":
        return None, "mismatch"

    lat, lon = coordinates(element)
    if lat is None or lon is None:
        # An OSM object without a current map location cannot be shown as a
        # confirmed destination on the map.
        return None, "mismatch"

    osm_id = str(candidate["id"])
    numeric_id = osm_id.split("/", 1)[1]
    name = str(tags.get("name") or f"{live_type} (OSM {numeric_id})").strip()
    return {
        **candidate,
        "name": name,
        "place_type": live_type,
        "lat": lat,
        "lon": lon,
        "description": describe(name, live_type, tags),
        "tags": tags,
        "verification_status": "confirmed_live_osm",
        "verification_source": "OpenStreetMap",
        "source_url": candidate.get("source_url") or f"https://www.openstreetmap.org/{osm_id}",
    }, None


async def verify_recommendations(
    candidates: list[dict[str, Any]],
    limit: int = 5,
    expected_categories: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check live OSM records in batches and continue past stale candidates.

    This makes real Overpass API calls. It never labels the cached Milvus row as
    checked when Overpass is unavailable, and it never returns an unchecked row.
    At most 20 candidates are checked per search to bound latency and load.
    """
    categories = expected_categories or []
    selected: list[dict[str, Any]] = []
    checked_count = 0
    excluded_closed = 0
    excluded_missing = 0
    excluded_mismatch = 0
    attempted_count = 0
    unavailable = False
    failure_reason = ""
    # Milvus has already relevance-ranked this pool. Preserve that order while
    # refilling the answer after closed, deleted, or reclassified records.
    checkable = candidates[:MAX_OSM_CHECKS]
    timeout = httpx.Timeout(8.0, connect=3.0)

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for offset in range(0, len(checkable), CHECK_BATCH_SIZE):
            batch = checkable[offset:offset + CHECK_BATCH_SIZE]
            attempted_count += sum(
                1 for candidate in batch
                if OSM_ID_PATTERN.fullmatch(str(candidate.get("id", "")))
            )
            try:
                live_records = await _fetch_live_batch(client, batch)
            except OSMVerificationUnavailable as exc:
                unavailable = True
                error_types = sorted(set(filter(None, exc.args[0].split("; ")))) if exc.args else []
                failure_reason = ", ".join(error_types) or "connection failure"
                break

            checked_count += sum(
                1 for candidate in batch
                if OSM_ID_PATTERN.fullmatch(str(candidate.get("id", "")))
            )
            for candidate in batch:
                live = live_records.get(str(candidate.get("id", "")))
                if live is None:
                    excluded_missing += 1
                    continue
                refreshed, reason = _refresh_from_live_osm(candidate, live, categories)
                if reason == "closed":
                    excluded_closed += 1
                    continue
                if refreshed is None:
                    excluded_mismatch += 1
                    continue
                selected.append(refreshed)
                if len(selected) >= limit:
                    break
            if len(selected) >= limit:
                break

    if unavailable and not selected:
        mode = "osm_unavailable"
        message = (
            "The live OpenStreetMap check did not respond. A recent local map snapshot may be used, "
            "but it will be clearly marked as not live-verified."
        )
    elif unavailable:
        mode = "osm_partial"
        message = (
            f"OpenStreetMap confirmed {len(selected)} place(s) before a later check failed. "
            "Only confirmed records are shown; try again for more results."
        )
    else:
        mode = "osm_live"
        message = (
            f"OpenStreetMap confirmed {len(selected)} current map record(s). "
            f"Skipped {excluded_closed} marked closed, {excluded_missing} removed, and "
            f"{excluded_mismatch} reclassified or mismatched record(s). A current map record "
            "does not guarantee the place is open or accepting visitors."
        )
    return selected[:limit], {
        "mode": mode,
        "checked_count": checked_count,
        "attempted_count": attempted_count,
        "verified_count": len(selected[:limit]),
        "excluded_closed_count": excluded_closed,
        "excluded_missing_count": excluded_missing,
        "excluded_mismatch_count": excluded_mismatch,
        "failure_reason": failure_reason,
        "message": message,
    }


def use_recent_snapshot(
    candidates: list[dict[str, Any]],
    verification: dict[str, Any],
    limit: int = 5,
    candidate_limit: int | None = None,
    expected_categories: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use a recent local OSM index only when live verification is unavailable.

    These records remain explicitly unverified. The saved source timestamp
    bounds how long this recovery path can be used; it is never a live check.
    """
    if verification.get("mode") != "osm_unavailable":
        return [], verification
    try:
        metadata = json.loads(SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
        date_text = metadata.get("snapshot_updated_at")
        updated_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")) if date_text else None
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        updated_at = None
    if updated_at is None:
        try:
            updated_at = datetime.fromtimestamp(CLEAN_PATH.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return [], verification
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (datetime.now(timezone.utc) - updated_at).total_seconds())
    age_days = int(age_seconds // 86400)
    if age_seconds > SNAPSHOT_MAX_AGE_DAYS * 86400:
        verification["message"] = (
            "The live OpenStreetMap check is unavailable, and the local map snapshot is older than "
            f"{SNAPSHOT_MAX_AGE_DAYS} days. No unverified places were shown. Refresh the OSM data and try again."
        )
        return [], verification

    categories = expected_categories or []
    snapshot_limit = min(max(candidate_limit or limit, limit), MAX_OSM_CHECKS)
    allowed_types = {
        place_type
        for category in categories
        for place_type in PLACE_TYPES_BY_CATEGORY.get(category, ())
    }
    selected: list[dict[str, Any]] = []
    for candidate in candidates[:MAX_OSM_CHECKS]:
        tags = candidate.get("tags") or {}
        if _osm_lifecycle_closed(tags):
            continue
        place_type = classify(tags)
        if place_type == "Place":
            continue
        if allowed_types and place_type not in allowed_types:
            continue
        if not allowed_types and place_type != str(candidate.get("place_type", "Place")):
            continue
        try:
            lat, lon = float(candidate["lat"]), float(candidate["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        osm_id = str(candidate.get("id", ""))
        if not OSM_ID_PATTERN.fullmatch(osm_id):
            continue
        selected.append({
            **candidate,
            "place_type": place_type,
            "lat": lat,
            "lon": lon,
            "verification_status": "osm_snapshot",
            "verification_source": "OpenStreetMap local snapshot",
            "snapshot_updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        })
        if len(selected) >= snapshot_limit:
            break

    if selected:
        date_label = updated_at.astimezone().strftime("%d %b %Y")
        age_label = "within the last 24 hours" if age_days == 0 else f"{age_days} day(s) ago"
        verification = {
            **verification,
            "mode": "osm_snapshot",
            "verified_count": 0,
            "snapshot_candidate_count": len(selected),
            "snapshot_updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            "snapshot_age_days": age_days,
            "message": (
                f"Live OpenStreetMap could not be reached. Ranking {len(selected)} candidates from the local "
                f"OSM snapshot, updated {date_label} ({age_label}). These records were not checked live; "
                "current existence and opening status are unknown."
            ),
        }
    else:
        verification["message"] = (
            "Live OpenStreetMap is unavailable and no category-matching places could be safely read "
            "from the recent local snapshot. Try again after reconnecting to the map service."
        )
    return selected, verification
