"""External-context study for Loto Lab.

This module is deliberately observational. Astrology is represented as a
cultural/symbolic label; astronomy, weather and earthquake-catalog fields are
kept separate. None of these fields are used to alter lottery predictions.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SYNODIC_MONTH_DAYS = 29.530588853
NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
PERMUTATIONS = 499
MIN_CORRELATION_SAMPLE = 15
MIN_EXPLORATORY_SAMPLE = 30
MIN_MONITORING_SAMPLE = 100
CACHE_TTL_SECONDS = 6 * 60 * 60

# Réglages provisoires fondés sur la documentation publique du Loto 5/35 Bet261.
# Le point est le centre approximatif du quartier Antaninarenina, pas une adresse vérifiée.
DEFAULT_DRAW_TIMEZONE = "Indian/Antananarivo"
DEFAULT_DRAW_LOCATION = {
    "latitude": -18.9103,
    "longitude": 47.52502,
    "name": "Antaninarenina, Antananarivo (approximatif)",
}

ZODIAC_SIGNS = (
    ("Capricorne", (1, 1), (1, 19)),
    ("Verseau", (1, 20), (2, 18)),
    ("Poissons", (2, 19), (3, 20)),
    ("Bélier", (3, 21), (4, 19)),
    ("Taureau", (4, 20), (5, 20)),
    ("Gémeaux", (5, 21), (6, 20)),
    ("Cancer", (6, 21), (7, 22)),
    ("Lion", (7, 23), (8, 22)),
    ("Vierge", (8, 23), (9, 22)),
    ("Balance", (9, 23), (10, 22)),
    ("Scorpion", (10, 23), (11, 21)),
    ("Sagittaire", (11, 22), (12, 21)),
    ("Capricorne", (12, 22), (12, 31)),
)

MOON_PHASES = (
    "Nouvelle lune",
    "Premier croissant",
    "Premier quartier",
    "Gibbeuse croissante",
    "Pleine lune",
    "Gibbeuse décroissante",
    "Dernier quartier",
    "Dernier croissant",
)

WEATHER_FIELDS = (
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_mean",
    "pressure_msl_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
    "cloud_cover_mean",
)

HOURLY_WEATHER_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "pressure_msl",
    "precipitation",
    "wind_speed_10m",
    "cloud_cover",
)

_CONTEXT_CACHE: dict[str, tuple[float, dict[str, Any], list[dict[str, Any]]]] = {}


def zodiac_sign(draw_date: date) -> str:
    """Return the conventional tropical Sun-sign label for the calendar date."""
    month_day = (draw_date.month, draw_date.day)
    for sign, start, end in ZODIAC_SIGNS:
        if start <= month_day <= end:
            return sign
    return "Capricorne"


def _draw_time_config() -> tuple[datetime_time, str]:
    raw_time = os.getenv("DRAW_TIME", "16:35").strip() or "16:35"
    try:
        draw_time = datetime_time.fromisoformat(raw_time)
        if draw_time.tzinfo is not None:
            raise ValueError("DRAW_TIME must be local wall-clock time without a UTC offset.")
    except ValueError:
        draw_time = datetime_time(16, 35)
    timezone_name = os.getenv("DRAW_TIMEZONE", DEFAULT_DRAW_TIMEZONE).strip() or DEFAULT_DRAW_TIMEZONE
    # "auto" used to interpret 16:35 as UTC; use Madagascar local time by default.
    if timezone_name.lower() == "auto":
        timezone_name = DEFAULT_DRAW_TIMEZONE
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone_name = DEFAULT_DRAW_TIMEZONE
    return draw_time.replace(second=0, microsecond=0), timezone_name


def lunar_context(
    draw_date: date,
    draw_time: datetime_time | str | None = None,
    timezone_name: str = "auto",
) -> dict[str, Any]:
    """Approximate lunar phase at the official local draw time.

    If no IANA time zone is configured, the clock is interpreted as UTC and
    the API explicitly marks this assumption instead of guessing the draw site.
    """
    if draw_time is None:
        draw_time, default_zone = _draw_time_config()
        if timezone_name == "auto":
            timezone_name = default_zone
    elif isinstance(draw_time, str):
        draw_time = datetime_time.fromisoformat(draw_time)

    local_moment = datetime.combine(draw_date, draw_time.replace(tzinfo=None))
    timezone_assumed = timezone_name == "auto"
    if timezone_assumed:
        local_moment = local_moment.replace(tzinfo=timezone.utc)
    else:
        try:
            local_moment = local_moment.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            local_moment = local_moment.replace(tzinfo=timezone.utc)
            timezone_assumed = True
    moment = local_moment.astimezone(timezone.utc)
    age = ((moment - NEW_MOON_EPOCH).total_seconds() / 86400) % SYNODIC_MONTH_DAYS
    phase = age / SYNODIC_MONTH_DAYS
    illumination = (1 - math.cos(2 * math.pi * phase)) / 2
    phase_index = int((phase * 8 + 0.5) % 8)
    return {
        "moon_age_days": round(age, 2),
        "moon_phase_fraction": round(phase, 4),
        "moon_illumination": round(illumination, 4),
        "moon_phase": MOON_PHASES[phase_index],
        "reference_time_local": draw_time.isoformat(timespec="minutes"),
        "reference_timezone": timezone_name,
        "reference_time_utc": moment.isoformat(timespec="minutes"),
        "timezone_assumed_utc": timezone_assumed,
    }


def _location_config() -> dict[str, Any]:
    draw_time, timezone_name = _draw_time_config()
    raw_lat = os.getenv("DRAW_LOCATION_LAT", "").strip()
    raw_lon = os.getenv("DRAW_LOCATION_LON", "").strip()
    use_default_location = not raw_lat and not raw_lon
    if use_default_location:
        raw_lat = str(DEFAULT_DRAW_LOCATION["latitude"])
        raw_lon = str(DEFAULT_DRAW_LOCATION["longitude"])
    elif not raw_lat or not raw_lon:
        return {
            "configured": False,
            "reason": "Les deux coordonnées DRAW_LOCATION_LAT et DRAW_LOCATION_LON doivent être renseignées ensemble.",
            "draw_time": draw_time.isoformat(timespec="minutes"),
            "timezone": timezone_name,
        }
    try:
        latitude = float(raw_lat)
        longitude = float(raw_lon)
    except ValueError:
        return {
            "configured": False,
            "reason": "Les coordonnées configurées ne sont pas numériques.",
            "draw_time": draw_time.isoformat(timespec="minutes"),
            "timezone": timezone_name,
        }
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {
            "configured": False,
            "reason": "Coordonnées géographiques hors limites.",
            "draw_time": draw_time.isoformat(timespec="minutes"),
            "timezone": timezone_name,
        }
    inferred_estimate = use_default_location or (
        math.isclose(latitude, DEFAULT_DRAW_LOCATION["latitude"], abs_tol=1e-5)
        and math.isclose(longitude, DEFAULT_DRAW_LOCATION["longitude"], abs_tol=1e-5)
    )
    estimate_override = os.getenv("DRAW_LOCATION_IS_ESTIMATE", "").strip().lower()
    if estimate_override in {"true", "1", "yes", "oui"}:
        location_is_estimate = True
    elif estimate_override in {"false", "0", "no", "non"} and not use_default_location:
        location_is_estimate = False
    else:
        # Missing coordinates always use an estimated default; setting false
        # cannot turn an unverified fallback into a confirmed physical venue.
        location_is_estimate = inferred_estimate
    try:
        radius = float(os.getenv("SEISMIC_RADIUS_KM", "200"))
    except ValueError:
        radius = 200.0
    try:
        min_magnitude = float(os.getenv("SEISMIC_MIN_MAGNITUDE", "2.5"))
    except ValueError:
        min_magnitude = 2.5
    if not 10 <= radius <= 20000:
        radius = 200.0
    if not 0 <= min_magnitude <= 9:
        min_magnitude = 2.5
    return {
        "configured": True,
        "latitude": latitude,
        "longitude": longitude,
        "name": (
            os.getenv("DRAW_LOCATION_NAME", "").strip()
            or (DEFAULT_DRAW_LOCATION["name"] if location_is_estimate else "Lieu du tirage")
        ),
        "location_is_estimate": location_is_estimate,
        "location_note": (
            "Point provisoire au centre du quartier Antaninarenina, à confirmer avec l'opérateur du tirage."
            if location_is_estimate else "Coordonnées personnalisées définies dans l'environnement de l'application."
        ),
        "timezone": timezone_name,
        "draw_time": draw_time.isoformat(timespec="minutes"),
        "seismic_radius_km": radius,
        "seismic_min_magnitude": min_magnitude,
    }


def _fetch_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "LotoLab-ContextStudy/1.0 (historical research)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Réponse de source externe inattendue.")
    if payload.get("error"):
        raise ValueError("La source externe a signalé une erreur.")
    return payload


def _fetch_weather(
    start_date: date, end_date: date, location: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Combine daily historical reanalysis with archived pre-draw forecast snapshots.

    Daily summaries are useful for descriptive charts. The contextual prediction
    model specifically consumes the archived forecast at 16:00 local time, so
    its training inputs better match the information available before the draw.
    """
    draw_time = datetime_time.fromisoformat(location.get("draw_time", "16:35"))
    reference_hour = draw_time.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")

    daily_params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(WEATHER_FIELDS),
        "timezone": location["timezone"],
    }
    daily_url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(daily_params)
    try:
        daily_payload = _fetch_json(daily_url)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        daily_payload = {}
    daily = daily_payload.get("daily") or {}
    dates = daily.get("time") or []
    by_date: dict[str, dict[str, Any]] = {}
    for index, day in enumerate(dates):
        item: dict[str, Any] = {}
        for field in WEATHER_FIELDS:
            values = daily.get(field) or []
            value = values[index] if index < len(values) else None
            item[field] = value
        by_date[day] = item

    # Same forecast models and response format as the live Forecast API,
    # archived historically from 2022 onward.
    forecast_params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "hourly": ",".join(HOURLY_WEATHER_FIELDS),
        "timezone": location["timezone"],
        "wind_speed_unit": "kmh",
    }
    forecast_url = (
        "https://historical-forecast-api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(forecast_params)
    )
    try:
        forecast_payload = _fetch_json(forecast_url)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        return by_date
    hourly = forecast_payload.get("hourly") or {}
    hourly_times = hourly.get("time") or []
    for index, timestamp in enumerate(hourly_times):
        try:
            local_timestamp = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            continue
        if local_timestamp.strftime("%H:%M") != reference_hour:
            continue
        day = local_timestamp.date().isoformat()
        item = by_date.setdefault(day, {})
        for field in HOURLY_WEATHER_FIELDS:
            values = hourly.get(field) or []
            item[f"{field}_at_draw_hour"] = values[index] if index < len(values) else None
        item["weather_reference_hour_local"] = reference_hour
        item["weather_context_source"] = "Open-Meteo Historical Forecast API"
    return by_date


def _fetch_weather_forecast(draw_date: date, location: dict[str, Any]) -> dict[str, Any]:
    """Fetch forecast weather at the local hour immediately before the 16:35 draw."""
    draw_time = datetime_time.fromisoformat(location.get("draw_time", "16:35"))
    reference_hour = draw_time.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "hourly": ",".join(HOURLY_WEATHER_FIELDS),
        "forecast_days": 16,
        "timezone": location["timezone"],
        "wind_speed_unit": "kmh",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    payload = _fetch_json(url)
    hourly = payload.get("hourly") or {}
    timestamps = hourly.get("time") or []
    target_timestamp = f"{draw_date.isoformat()}T{reference_hour}"
    index = next((i for i, value in enumerate(timestamps) if value == target_timestamp), None)
    if index is None:
        raise ValueError("La prévision horaire Open-Meteo ne couvre pas la date du prochain tirage.")
    result: dict[str, Any] = {"weather_reference_hour_local": reference_hour}
    for field in HOURLY_WEATHER_FIELDS:
        values = hourly.get(field) or []
        result[f"{field}_at_draw_hour"] = values[index] if index < len(values) else None
    if sum(value is not None for key, value in result.items() if key.endswith("_at_draw_hour")) < 3:
        raise ValueError("Prévision Open-Meteo incomplète pour l'heure du tirage.")
    result["weather_source"] = "Open-Meteo Forecast API"
    result["weather_forecast_time_local"] = target_timestamp
    return result


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _date_chunks(start_date: date, end_date: date, max_days: int = 1700):
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(end_date, cursor + timedelta(days=max_days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _summarize_seismic_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    magnitudes = [
        float(event["magnitude"])
        for event in events
        if event.get("magnitude") is not None
    ]
    distances = [float(event["distance_km"]) for event in events]
    nearest_event = min(events, key=lambda event: event["distance_km"]) if events else None
    return {
        "earthquake_count": len(events),
        "max_magnitude": max(magnitudes) if magnitudes else 0.0,
        "nearest_distance_km": min(distances) if distances else None,
        "nearest_depth_km": nearest_event["depth_km"] if nearest_event else None,
        "events": sorted(events, key=lambda event: event["distance_km"])[:5],
        "seismic_window_hours": 24,
    }


def _fetch_recent_seismic_snapshot(
    location: dict[str, Any],
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return catalogued events in the 24 hours before the current prediction snapshot."""
    end_time = as_of or datetime.now(timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    end_time = end_time.astimezone(timezone.utc)
    start_time = end_time - timedelta(hours=24)
    params = {
        "format": "geojson",
        "starttime": start_time.isoformat(timespec="seconds"),
        "endtime": end_time.isoformat(timespec="seconds"),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "maxradiuskm": location["seismic_radius_km"],
        "minmagnitude": location["seismic_min_magnitude"],
        "orderby": "time-asc",
        "limit": 1000,
    }
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(params)
    payload = _fetch_json(url)
    events = []
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 3 or properties.get("time") is None:
            continue
        longitude, latitude, depth = coordinates[:3]
        distance = _haversine_km(
            location["latitude"], location["longitude"], float(latitude), float(longitude)
        )
        event_time = datetime.fromtimestamp(properties["time"] / 1000, tz=timezone.utc)
        events.append({
            "id": feature.get("id"),
            "time_utc": event_time.isoformat(),
            "magnitude": properties.get("mag"),
            "depth_km": depth,
            "distance_km": round(distance, 1),
            "place": properties.get("place"),
            "url": properties.get("url"),
        })
    summary = _summarize_seismic_events(events)
    summary["snapshot_time_utc"] = end_time.isoformat(timespec="seconds")
    summary["window_start_utc"] = start_time.isoformat(timespec="seconds")
    summary["available"] = True
    return summary


def _fetch_seismic(
    start_date: date, end_date: date, location: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Build a no-look-ahead 24-hour seismic window ending at each draw cutoff."""
    events_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    timezone_name = location.get("timezone", DEFAULT_DRAW_TIMEZONE)
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = ZoneInfo(DEFAULT_DRAW_TIMEZONE)
    draw_time = datetime_time.fromisoformat(location.get("draw_time", "16:35"))
    seen_event_keys: set[str] = set()
    for chunk_start, chunk_end in _date_chunks(start_date, end_date):
        params = {
            "format": "geojson",
            "starttime": (chunk_start - timedelta(days=2)).isoformat(),
            "endtime": (chunk_end + timedelta(days=2)).isoformat(),
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "maxradiuskm": location["seismic_radius_km"],
            "minmagnitude": location["seismic_min_magnitude"],
            "orderby": "time-asc",
            "limit": 2000,
        }
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(params)
        payload = _fetch_json(url)
        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            coordinates = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coordinates) < 3 or properties.get("time") is None:
                continue
            longitude, latitude, depth = coordinates[:3]
            event_time = datetime.fromtimestamp(properties["time"] / 1000, tz=timezone.utc)
            local_event_time = event_time.astimezone(local_timezone)
            event_day = local_event_time.date()
            event_key = str(feature.get("id") or f"{event_time.isoformat()}:{latitude}:{longitude}")
            if event_key in seen_event_keys:
                continue
            seen_event_keys.add(event_key)
            distance = _haversine_km(
                location["latitude"], location["longitude"], float(latitude), float(longitude)
            )
            event = {
                "id": feature.get("id"),
                "time_utc": event_time.isoformat(),
                "magnitude": properties.get("mag"),
                "depth_km": depth,
                "distance_km": round(distance, 1),
                "place": properties.get("place"),
                "url": properties.get("url"),
            }
            for draw_day in (event_day, event_day + timedelta(days=1)):
                if not start_date <= draw_day <= end_date:
                    continue
                cutoff_local = datetime.combine(draw_day, draw_time, tzinfo=local_timezone)
                if cutoff_local - timedelta(hours=24) <= event_time <= cutoff_local:
                    events_by_date[draw_day.isoformat()].append(event)
    return {
        (start_date + timedelta(days=index)).isoformat(): _summarize_seismic_events(
            events_by_date.get((start_date + timedelta(days=index)).isoformat(), [])
        )
        for index in range((end_date - start_date).days + 1)
    }


def _external_context(
    start_date: date, end_date: date, location: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cache_payload = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "lat": location["latitude"],
        "lon": location["longitude"],
        "timezone": location["timezone"],
        "draw_time": location["draw_time"],
        "radius": location["seismic_radius_km"],
        "min_mag": location["seismic_min_magnitude"],
    }
    cache_key = json.dumps(cache_payload, sort_keys=True)
    now = time.monotonic()
    cached = _CONTEXT_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    statuses = {
        "weather_available": False,
        "seismic_available": False,
        "weather_error": None,
        "seismic_error": None,
    }
    weather: dict[str, dict[str, Any]] = {}
    seismic: dict[str, dict[str, Any]] = {}
    try:
        weather = _fetch_weather(start_date, end_date, location)
        statuses["weather_available"] = bool(weather)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        statuses["weather_error"] = "Archives météorologiques momentanément indisponibles."
    try:
        seismic = _fetch_seismic(start_date, end_date, location)
        statuses["seismic_available"] = True
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        statuses["seismic_error"] = "Catalogue sismique momentanément indisponible."
    merged = []
    cursor = start_date
    while cursor <= end_date:
        day = cursor.isoformat()
        merged.append({
            "date": day,
            "weather": weather.get(day),
            "seismic": seismic.get(day, {
                "earthquake_count": 0,
                "max_magnitude": None,
                "nearest_distance_km": None,
                "events": [],
            }),
        })
        cursor += timedelta(days=1)

    if len(_CONTEXT_CACHE) >= 16:
        _CONTEXT_CACHE.pop(next(iter(_CONTEXT_CACHE)))
    _CONTEXT_CACHE[cache_key] = (now + CACHE_TTL_SECONDS, statuses, merged)
    return statuses, merged


def _rank(values: list[float]) -> list[float]:
    """Average ranks with ties, using 1-based ranks."""
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = average_rank
        index = end
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    dx = [value - mean_x for value in x]
    dy = [value - mean_y for value in y]
    denominator = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denominator


def _permutation_p_value(x: list[float], y: list[float], key: str) -> tuple[float | None, float | None]:
    rx, ry = _rank(x), _rank(y)
    observed = _pearson(rx, ry)
    if observed is None:
        return None, None
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(PERMUTATIONS):
        shuffled = rng.sample(ry, len(ry))
        value = _pearson(rx, shuffled)
        if value is not None and abs(value) >= abs(observed) - 1e-12:
            extreme += 1
    return observed, (extreme + 1) / (PERMUTATIONS + 1)


def _holm_adjust(tests: list[dict[str, Any]]) -> None:
    ordered = sorted(
        (row for row in tests if row.get("p_value") is not None),
        key=lambda row: row["p_value"],
    )
    count = len(ordered)
    running = 0.0
    for index, row in enumerate(ordered):
        adjusted = min(1.0, (count - index) * row["p_value"])
        running = max(running, adjusted)
        row["p_adjusted"] = running


def _correlations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    predictors = (
        ("moon_illumination", "Éclairement lunaire"),
        ("moon_age_days", "Âge de la Lune"),
        ("temperature_2m_mean", "Température moyenne quotidienne"),
        ("temperature_2m_max", "Température maximale quotidienne"),
        ("relative_humidity_2m_mean", "Humidité moyenne quotidienne"),
        ("pressure_msl_mean", "Pression moyenne quotidienne"),
        ("precipitation_sum", "Précipitations quotidiennes"),
        ("wind_speed_10m_max", "Vent maximal quotidien"),
        ("cloud_cover_mean", "Nébulosité moyenne quotidienne"),
        ("temperature_2m_at_draw_hour", "Température vers 16:00 locale"),
        ("relative_humidity_2m_at_draw_hour", "Humidité vers 16:00 locale"),
        ("pressure_msl_at_draw_hour", "Pression vers 16:00 locale"),
        ("precipitation_at_draw_hour", "Précipitations de l'heure précédente"),
        ("wind_speed_10m_at_draw_hour", "Vent vers 16:00 locale"),
        ("cloud_cover_at_draw_hour", "Nébulosité vers 16:00 locale"),
        ("earthquake_count", "Nombre de séismes catalogués"),
        ("max_magnitude", "Magnitude maximale"),
        ("nearest_distance_km", "Distance du séisme le plus proche"),
    )
    outcomes = (
        ("draw_sum", "Somme des 5 numéros"),
        ("draw_range", "Amplitude (max − min)"),
        ("odd_count", "Nombre de numéros impairs"),
        ("low_count", "Nombre de numéros de 1 à 17"),
        ("overlap_previous", "Numéros communs avec le tirage précédent"),
    )
    tests: list[dict[str, Any]] = []
    for predictor, predictor_label in predictors:
        for outcome, outcome_label in outcomes:
            x: list[float] = []
            y: list[float] = []
            for row in rows:
                xv, yv = row.get(predictor), row.get(outcome)
                if xv is None or yv is None:
                    continue
                x.append(float(xv))
                y.append(float(yv))
            if len(x) < MIN_CORRELATION_SAMPLE:
                continue
            rho, p_value = _permutation_p_value(x, y, f"{predictor}:{outcome}:{len(x)}")
            if rho is None or p_value is None:
                continue
            tests.append({
                "factor": predictor,
                "factor_label": predictor_label,
                "outcome": outcome,
                "outcome_label": outcome_label,
                "sample_size": len(x),
                "spearman_rho": round(rho, 4),
                "p_value": round(p_value, 4),
                "p_adjusted": None,
            })
    _holm_adjust(tests)
    for row in tests:
        if row["p_adjusted"] is not None:
            row["p_adjusted"] = round(row["p_adjusted"], 4)
            row["flag"] = "signal_statistique_a_repliquer" if row["p_adjusted"] <= 0.05 else "non_significatif"
    tests.sort(key=lambda row: (
        row.get("p_adjusted") is None,
        row.get("p_adjusted") if row.get("p_adjusted") is not None else 1,
        -abs(row["spearman_rho"]),
    ))
    return {
        "tests_count": len(tests),
        "significant_count": sum(row.get("p_adjusted", 1) <= 0.05 for row in tests),
        "minimum_sample": MIN_CORRELATION_SAMPLE,
        "method": "Corrélation de Spearman, p-value par permutation déterministe, correction Holm des tests multiples.",
        "results": tests[:30],
    }


def _group_statistics(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    result = []
    for label, members in sorted(groups.items(), key=lambda item: -len(item[1])):
        result.append({
            "label": label,
            "draw_count": len(members),
            "average_draw_sum": round(
                sum(row["draw_sum"] for row in members) / len(members), 2
            ),
            "average_odd_count": round(
                sum(row["odd_count"] for row in members) / len(members), 2
            ),
        })
    return result


def build_contextual_study(
    raw_draws: Iterable[dict[str, Any]],
    *,
    include_all_rows: bool = False,
) -> dict[str, Any]:
    """Build an observational dataset; do not alter any prediction scores."""
    draws = []
    for item in raw_draws:
        draw_date = item["date"]
        if isinstance(draw_date, str):
            draw_date = date.fromisoformat(draw_date)
        numbers = sorted(int(number) for number in item["numbers"])
        if len(numbers) != 5 or len(set(numbers)) != 5 or any(n < 1 or n > 35 for n in numbers):
            raise ValueError("Chaque tirage doit contenir 5 numéros distincts de 1 à 35.")
        draws.append({"date": draw_date, "numbers": numbers})
    draws.sort(key=lambda item: item["date"])

    location = _location_config()
    rows: list[dict[str, Any]] = []
    previous_numbers: set[int] | None = None
    for draw in draws:
        numbers = draw["numbers"]
        astro = lunar_context(
            draw["date"],
            location["draw_time"],
            location["timezone"],
        )
        rows.append({
            "date": draw["date"].isoformat(),
            "numbers": numbers,
            "zodiac_sign": zodiac_sign(draw["date"]),
            **astro,
            "draw_sum": sum(numbers),
            "draw_range": max(numbers) - min(numbers),
            "odd_count": sum(number % 2 for number in numbers),
            "low_count": sum(number <= 17 for number in numbers),
            "overlap_previous": (
                len(set(numbers) & previous_numbers) if previous_numbers is not None else None
            ),
        })
        previous_numbers = set(numbers)

    source_status = {
        "weather_available": False,
        "seismic_available": False,
        "weather_error": None,
        "seismic_error": None,
    }
    weather_rows: list[dict[str, Any]] = []
    if draws and location["configured"]:
        source_status, weather_rows = _external_context(
            draws[0]["date"], draws[-1]["date"], location
        )
        environment_by_date = {row["date"]: row for row in weather_rows}
        for row in rows:
            context = environment_by_date.get(row["date"], {})
            weather = context.get("weather") or {}
            seismic = context.get("seismic") or {}
            row.update(weather)
            seismic_data_available = source_status.get("seismic_available", False)
            row.update({
                "earthquake_count": seismic.get("earthquake_count", 0) if seismic_data_available else None,
                "max_magnitude": seismic.get("max_magnitude") if seismic_data_available else None,
                "nearest_distance_km": seismic.get("nearest_distance_km") if seismic_data_available else None,
                "nearest_depth_km": seismic.get("nearest_depth_km") if seismic_data_available else None,
                "seismic_events": seismic.get("events", []) if seismic_data_available else [],
            })
    else:
        for row in rows:
            row.update({
                "earthquake_count": None,
                "max_magnitude": None,
                "nearest_distance_km": None,
                "nearest_depth_km": None,
                "seismic_events": [],
            })

    draw_count = len(rows)
    if draw_count < 30:
        sample_level = "insufficient"
        sample_note = "Historique trop court pour une lecture statistique exploratoire robuste."
    elif draw_count < MIN_MONITORING_SAMPLE:
        sample_level = "exploratory"
        sample_note = "Résultats exploratoires : échantillon limité, aucune conclusion prédictive."
    else:
        sample_level = "monitoring"
        sample_note = "Échantillon plus large, mais tout signal doit encore être répliqué sur de nouveaux tirages."
    correlations = _correlations(rows) if draw_count >= MIN_EXPLORATORY_SAMPLE else {
        "tests_count": 0,
        "significant_count": 0,
        "minimum_sample": MIN_CORRELATION_SAMPLE,
        "method": "Les tests de corrélation seront proposés à partir de 30 tirages.",
        "results": [],
    }
    return {
        "meta": {
            "draw_count": draw_count,
            "sample_level": sample_level,
            "sample_note": sample_note,
            "location_configured": location["configured"],
            "location_name": location.get("name"),
            "location_is_estimate": location.get("location_is_estimate", False),
            "location_note": location.get("location_note"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "timezone": location.get("timezone"),
            "draw_time": location.get("draw_time", "16:35"),
            "weather_reference_hour_local": datetime_time.fromisoformat(location.get("draw_time", "16:35")).replace(minute=0).isoformat(timespec="minutes"),
            "timezone_assumed_utc": location.get("timezone", "auto") == "auto",
            "seismic_radius_km": location.get("seismic_radius_km"),
            "seismic_min_magnitude": location.get("seismic_min_magnitude"),
            **source_status,
        },
        "methodology": {
            "astrology": "Signe solaire tropical calculé à partir de la date ; information symbolique, non validée comme facteur prédictif.",
            "astronomy": "Phase et éclairement lunaires approximatifs calculés à 16:35 heure locale de Madagascar par défaut, avec conversion en UTC via Indian/Antananarivo ; un fuseau différent peut être fourni par DRAW_TIMEZONE.",
            "weather": "Open-Meteo fournit à la fois des résumés quotidiens et des valeurs horaires ; les colonnes de contexte utilisent l'heure locale arrondie à l'heure inférieure (16:00 pour un tirage à 16:35), comme approximation et sans information future. Les précipitations horaires couvrent l'heure précédente ; les archives sont des données de réanalyse, pas des mesures garanties au point exact.",
            "seismic": "Catalogue USGS limité pour chaque tirage aux 24 heures précédant l'heure locale de coupure (16:35 par défaut) ; il s'agit d'événements catalogués et non de mesures de forme d'onde ou d'accélération du sol sur place.",
            "prediction_policy": "Les variables externes sont évaluées par un moteur contextuel expérimental séparé ; leur poids reste limité et leur performance est contrôlée par validation chronologique.",
        },
        "correlations": correlations,
        "zodiac_groups": _group_statistics(rows, "zodiac_sign") if rows else [],
        "moon_groups": _group_statistics(rows, "moon_phase") if rows else [],
        "rows": (rows if include_all_rows else rows[-40:])[::-1],
    }
