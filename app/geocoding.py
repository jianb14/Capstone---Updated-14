"""Cached Philippine place lookup shared by booking search and shop resolution."""

import hashlib
import math

import requests
from django.conf import settings
from django.core.cache import cache


class GeocodingUnavailable(Exception):
    pass


def valid_coordinates(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
        return math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180
    except (ValueError, TypeError, OverflowError):
        return False


def _lookup(path, params):
    base = getattr(settings, "BOOKING_GEOCODER_URL", "https://photon.komoot.io").rstrip("/")
    key = "booking-geocode:" + hashlib.sha256(
        (base + path + repr(sorted(params.items()))).encode()
    ).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        response = requests.get(
            base + path, params=params, timeout=(3, 6),
            headers={"User-Agent": "BalloorinaBooking/1.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        rows = []
        for feature in features:
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2 or not valid_coordinates(coords[1], coords[0]):
                continue
            # The bounding box includes some neighbouring islands; country is authoritative.
            if str(props.get("countrycode", "")).upper() != "PH":
                continue
            parts = []
            street = " ".join(str(props.get(k) or "") for k in ("housenumber", "street")).strip()
            for value in [props.get("name"), street, props.get("district"), props.get("city"),
                          props.get("county"), props.get("state"), props.get("postcode"), "Philippines"]:
                if value and str(value).casefold() not in [p.casefold() for p in parts]:
                    parts.append(str(value))
            rows.append({"display_name": ", ".join(parts), "lat": coords[1], "lon": coords[0]})
        cache.set(key, rows, 86400 if rows else 60)
        return rows
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        raise GeocodingUnavailable("Place lookup is temporarily unavailable.") from exc


def search_places(query):
    return _lookup("/api/", {
        "q": query, "limit": 8, "lang": "en", "bbox": "116,4,127,22",
        "lat": 14.4, "lon": 120.95,
    })


def reverse_place(lat, lng):
    return _lookup("/reverse/", {"lat": lat, "lon": lng, "limit": 1, "lang": "en"})
