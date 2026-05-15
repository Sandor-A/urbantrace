from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / "data" / "geocache.json"
_cache_lock = threading.Lock()

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    _GEOPY_AVAILABLE = True
except ImportError:
    _GEOPY_AVAILABLE = False
    logger.info(
        "geopy not installed — real geocoding disabled. "
        "Enable with: pip install geopy"
    )


def _load_cache() -> dict[str, Any]:
    try:
        if _CACHE_PATH.exists():
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        _CACHE_PATH.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Could not save geocache: %s", e)


def _geocode_one(geocoder: Any, address: str) -> dict[str, Any]:
    """Call Nominatim for a single address. Returns empty dict on failure."""
    try:
        time.sleep(1.1)  # Nominatim enforces 1 req/s; add a small buffer
        result = geocoder.geocode(
            f"{address}, Cluj-Napoca, Romania",
            addressdetails=True,
            language="ro",
        )
        if not result:
            return {}
        parts = result.raw.get("address", {})
        neighborhood = (
            parts.get("neighbourhood")
            or parts.get("suburb")
            or parts.get("quarter")
            or parts.get("city_district")
        )
        return {
            "lat": result.latitude,
            "lng": result.longitude,
            "geo_neighborhood": neighborhood,
        }
    except (GeocoderTimedOut, GeocoderServiceError, Exception) as exc:
        logger.debug("Geocoding failed for %r: %s", address, exc)
        return {}


def _run_geocoding(properties: list[dict[str, Any]]) -> None:
    """Worker: geocodes uncached properties and writes results to cache."""
    with _cache_lock:
        cache = _load_cache()

    uncached = [
        p for p in properties
        if str(p.get("propkey", "")) not in cache
    ]
    if not uncached:
        return

    logger.info(
        "Geocoding %d uncached properties via Nominatim (OSM)… "
        "This runs in the background; existing borough data is used in the meantime.",
        len(uncached),
    )

    geocoder = Nominatim(user_agent="urbantrace-research/1.0", timeout=8)
    batch: dict[str, Any] = {}

    for prop in uncached:
        key = str(prop.get("propkey", ""))
        address = str(prop.get("address", "")).strip()
        entry = _geocode_one(geocoder, address) if address else {}
        batch[key] = entry

        # Flush cache every 50 entries so progress is not lost on interruption
        if len(batch) % 50 == 0:
            with _cache_lock:
                merged = _load_cache()
                merged.update(batch)
                _save_cache(merged)
            batch = {}

    if batch:
        with _cache_lock:
            merged = _load_cache()
            merged.update(batch)
            _save_cache(merged)

    # Patch in-memory property dicts with freshly geocoded data
    with _cache_lock:
        final_cache = _load_cache()
    for prop in properties:
        key = str(prop.get("propkey", ""))
        entry = final_cache.get(key, {})
        if entry:
            prop["lat"] = entry.get("lat")
            prop["lng"] = entry.get("lng")
            prop["geo_neighborhood"] = entry.get("geo_neighborhood")

    logger.info("Background geocoding complete.")


def enrich_with_geocoding(properties: list[dict[str, Any]]) -> None:
    """
    Enrich each property dict in-place with lat, lng, and geo_neighborhood.

    - Reads from cache instantly for already-geocoded properties.
    - Kicks off background geocoding for uncached properties (non-blocking).
    - Works safely without geopy installed (fields set to None).
    """
    cache = _load_cache()

    # Apply whatever is already cached immediately (no blocking)
    for prop in properties:
        entry = cache.get(str(prop.get("propkey", "")), {})
        prop.setdefault("lat", entry.get("lat"))
        prop.setdefault("lng", entry.get("lng"))
        prop.setdefault("geo_neighborhood", entry.get("geo_neighborhood"))

    if not _GEOPY_AVAILABLE:
        return

    # Anything not in cache gets geocoded in a daemon thread
    uncached = [
        p for p in properties
        if str(p.get("propkey", "")) not in cache
    ]
    if uncached:
        thread = threading.Thread(
            target=_run_geocoding, args=(properties,), daemon=True, name="geocoder"
        )
        thread.start()
