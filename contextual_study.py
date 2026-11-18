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
    except ValueError:
        draw_time = datetime_time(16, 35)
    timezone_name = os.getenv("DRAW_TIMEZONE", "auto").strip() or "auto"
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
    if not raw_lat or not raw_lon:
        return {
            "configured": False,
            "reason": "Coordonnées du lieu du tirage non configurées.",
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
        return {"configured": False, "reason": "Coordonnées géographiques hors limites."}
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
        "name": os.getenv("DRAW_LOCATION_NAME", "Lieu du tirage").strip() or "Lieu du tirage",
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
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(WEATHER_FIELDS),
        "timezone": location["timezone"],
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    payload = _fetch_json(url)
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    by_date: dict[str, dict[str, Any]] = {}
    for index, day in enumerate(dates):
        item: dict[str, Any] = {}
        for field in WEATHER_FIELDS:
            values = daily.get(field) or []
            value = values[index] if index < len(values) else None
            item[field] = value
        by_date[day] = item
    return by_date


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


def _fetch_seismic(
    start_date: date, end_date: date, location: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    events_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    timezone_name = location.get("timezone", "auto")
    try:
        local_timezone = ZoneInfo(timezone_name) if timezone_name != "auto" else timezone.utc
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    seen_event_keys: set[str] = set()
    for chunk_start, chunk_end in _date_chunks(start_date, end_date):
        params = {
            "format": "geojson",
            # Include a margin so UTC catalogue events can be assigned to a local
            # draw date even when the configured time zone is not UTC.
            "starttime": (chunk_start - timedelta(days=1)).isoformat(),
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
            event_day = event_time.astimezone(local_timezone).date().isoformat()
            event_key = str(feature.get("id") or f"{event_time.isoformat()}:{latitude}:{longitude}")
            if event_key in seen_event_keys:
                continue
            seen_event_keys.add(event_key)
            if not start_date.isoformat() <= event_day <= end_date.isoformat():
                continue
            distance = _haversine_km(
                location["latitude"], location["longitude"], float(latitude), float(longitude)
            )
            events_by_date[event_day].append({
                "id": feature.get("id"),
                "time_utc": event_time.isoformat(),
                "magnitude": properties.get("mag"),
                "depth_km": depth,
                "distance_km": round(distance, 1),
                "place": properties.get("place"),
                "url": properties.get("url"),
            })
    result = {}
    for day, events in events_by_date.items():
        magnitudes = [float(event["magnitude"]) for event in events if event["magnitude"] is not None]
        distances = [float(event["distance_km"]) for event in events]
        nearest_event = min(events, key=lambda event: event["distance_km"]) if events else None
        result[day] = {
            "earthquake_count": len(events),
            "max_magnitude": max(magnitudes) if magnitudes else None,
            "nearest_distance_km": min(distances) if distances else None,
            "nearest_depth_km": nearest_event["depth_km"] if nearest_event else None,
            "events": sorted(events, key=lambda event: event["distance_km"])[:5],
        }
    return result


def _external_context(
    start_date: date, end_date: date, location: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cache_payload = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "lat": location["latitude"],
        "lon": location["longitude"],
        "timezone": location["timezone"],
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
        ("temperature_2m_mean", "Température moyenne"),
        ("temperature_2m_max", "Température maximale"),
        ("relative_humidity_2m_mean", "Humidité moyenne"),
        ("pressure_msl_mean", "Pression au niveau de la mer"),
        ("precipitation_sum", "Précipitations"),
        ("wind_speed_10m_max", "Vent maximal"),
        ("cloud_cover_mean", "Nébulosité moyenne"),
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


def build_contextual_study(raw_draws: Iterable[dict[str, Any]]) -> dict[str, Any]:
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
            row.update({
                "earthquake_count": seismic.get("earthquake_count", 0),
                "max_magnitude": seismic.get("max_magnitude"),
                "nearest_distance_km": seismic.get("nearest_distance_km"),
                "nearest_depth_km": seismic.get("nearest_depth_km"),
                "seismic_events": seismic.get("events", []),
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
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "timezone": location.get("timezone"),
            "draw_time": location.get("draw_time", "16:35"),
            "timezone_assumed_utc": location.get("timezone", "auto") == "auto",
            "seismic_radius_km": location.get("seismic_radius_km"),
            "seismic_min_magnitude": location.get("seismic_min_magnitude"),
            **source_status,
        },
        "methodology": {
            "astrology": "Signe solaire tropical calculé à partir de la date ; information symbolique, non validée comme facteur prédictif.",
            "astronomy": "Phase et éclairement lunaires approximatifs calculés au moment de référence local du tirage, avec conversion en UTC via DRAW_TIMEZONE ; si le fuseau n'est pas configuré, l'heure est interprétée comme UTC et cette hypothèse est signalée.",
            "weather": "Valeurs quotidiennes historiques de réanalyse Open-Meteo ; elles ne sont pas nécessairement des mesures locales au point exact.",
            "seismic": "Catalogue d'événements sismiques USGS dans le rayon configuré ; les horodatages sont ramenés au fuseau DRAW_TIMEZONE si celui-ci est configuré. Ce ne sont pas des mesures de forme d'onde ou d'accélération du sol à l'endroit du tirage.",
            "prediction_policy": "Aucune variable externe n'entre dans les scores ou les combinaisons de prédiction.",
        },
        "correlations": correlations,
        "zodiac_groups": _group_statistics(rows, "zodiac_sign") if rows else [],
        "moon_groups": _group_statistics(rows, "moon_phase") if rows else [],
        "rows": rows[-40:][::-1],
    }
