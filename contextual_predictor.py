"""Context-aware experimental 5/35 scoring using pre-draw external observations.

The model compares a forecast context with past draw contexts and uses a
strongly-shrunk, bounded adjustment to the historical number scores. It is
not a claim that weather, astronomy, astrology, or earthquakes cause lottery
results. All historical predictors are restricted to information available
by the 16:35 draw cutoff.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from analysis_engine import BASE_RATE, N_NUMBERS, PICK_COUNT, _clean_draws, _number_scores
from contextual_study import (
    DEFAULT_DRAW_TIMEZONE,
    ZODIAC_SIGNS,
    _fetch_recent_seismic_snapshot,
    _fetch_weather_forecast,
    _location_config,
    build_contextual_study,
    lunar_context,
    zodiac_sign,
)

MIN_TRAINING_DRAWS = 30
MAX_HISTORY_DRAWS = 365
MAX_NEIGHBORS = 30
CONTEXT_PRIOR_DRAWS = 12.0
_PREDICTION_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PREDICTION_CACHE_TTL_SECONDS = 15 * 60

FEATURE_WEIGHTS = {
    "moon_sin": 0.8,
    "moon_cos": 0.8,
    "zodiac_sin": 0.2,
    "zodiac_cos": 0.2,
    "temperature": 1.0,
    "humidity": 1.0,
    "pressure": 0.9,
    "precipitation": 0.7,
    "wind": 0.7,
    "cloud": 0.7,
    "earthquake_count": 0.5,
    "earthquake_max_magnitude": 0.4,
    "earthquake_nearest_distance": 0.4,
}
WEATHER_FEATURES = {
    "temperature", "humidity", "pressure", "precipitation", "wind", "cloud"
}
FEATURE_LABELS = {
    "moon_sin": "Phase lunaire",
    "moon_cos": "Phase lunaire",
    "zodiac_sin": "Signe zodiacal symbolique",
    "zodiac_cos": "Signe zodiacal symbolique",
    "temperature": "Température à 16 h",
    "humidity": "Humidité à 16 h",
    "pressure": "Pression à 16 h",
    "precipitation": "Précipitations de 15 h à 16 h",
    "wind": "Vent à 16 h",
    "cloud": "Nébulosité à 16 h",
    "earthquake_count": "Séismes catalogués sur les dernières 24 h",
    "earthquake_max_magnitude": "Magnitude maximale sur les dernières 24 h",
    "earthquake_nearest_distance": "Distance du séisme le plus proche sur 24 h",
}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _feature_vector(row: dict[str, Any], seismic_radius_km: float) -> dict[str, float]:
    """Convert one historical or forecast context into a comparable numeric vector."""
    features: dict[str, float] = {}
    phase = _as_float(row.get("moon_phase_fraction"))
    if phase is not None:
        features["moon_sin"] = math.sin(2 * math.pi * phase)
        features["moon_cos"] = math.cos(2 * math.pi * phase)

    sign = row.get("zodiac_sign")
    sign_index = next(
        (index for index, item in enumerate(ZODIAC_SIGNS) if item[0] == sign),
        None,
    )
    if sign_index is not None:
        angle = 2 * math.pi * sign_index / 12
        features["zodiac_sin"] = math.sin(angle)
        features["zodiac_cos"] = math.cos(angle)

    weather_fields = (
        ("temperature", "temperature_2m_at_draw_hour"),
        ("humidity", "relative_humidity_2m_at_draw_hour"),
        ("pressure", "pressure_msl_at_draw_hour"),
        ("precipitation", "precipitation_at_draw_hour"),
        ("wind", "wind_speed_10m_at_draw_hour"),
        ("cloud", "cloud_cover_at_draw_hour"),
    )
    for feature_name, field_name in weather_fields:
        value = _as_float(row.get(field_name))
        if value is not None:
            features[feature_name] = value

    quake_count = _as_float(row.get("earthquake_count"))
    if quake_count is not None:
        features["earthquake_count"] = quake_count
        magnitude = _as_float(row.get("max_magnitude"))
        distance = _as_float(row.get("nearest_distance_km"))
        features["earthquake_max_magnitude"] = magnitude if magnitude is not None else 0.0
        # No event in the requested radius is a valid observation, not a missing value.
        features["earthquake_nearest_distance"] = (
            distance if distance is not None else float(seismic_radius_km)
        )
    return features


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 1.0
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _feature_scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Robust per-feature scales, so hPa, degrees, and ratios are comparable."""
    scales: dict[str, float] = {}
    floors = {
        "moon_sin": 0.35, "moon_cos": 0.35, "zodiac_sin": 0.35, "zodiac_cos": 0.35,
        "temperature": 2.0, "humidity": 8.0, "pressure": 3.0,
        "precipitation": 0.5, "wind": 3.0, "cloud": 12.0,
        "earthquake_count": 1.0, "earthquake_max_magnitude": 0.5,
        "earthquake_nearest_distance": 40.0,
    }
    names = set().union(*(row.keys() for row in rows)) if rows else set()
    for name in names:
        values = [float(row[name]) for row in rows if row.get(name) is not None]
        if len(values) < 2:
            scales[name] = floors.get(name, 1.0)
            continue
        iqr_scale = (_quantile(values, 0.75) - _quantile(values, 0.25)) / 1.349
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_scale = math.sqrt(variance)
        scales[name] = max(iqr_scale, standard_scale * 0.5, floors.get(name, 0.1))
    return scales


def _context_distance(
    left: dict[str, float],
    right: dict[str, float],
    scales: dict[str, float],
) -> float | None:
    common = set(left) & set(right)
    if len(common) < 6 or len(common & WEATHER_FEATURES) < 3:
        return None
    weighted_squared = 0.0
    weight_total = 0.0
    for name in common:
        weight = FEATURE_WEIGHTS.get(name, 0.0)
        if weight <= 0:
            continue
        scale = max(scales.get(name, 1.0), 1e-9)
        difference = (left[name] - right[name]) / scale
        weighted_squared += weight * difference * difference
        weight_total += weight
    return math.sqrt(weighted_squared / weight_total) if weight_total else None


def _rank_contextual(
    training_draws: list[dict[str, Any]],
    training_contexts: list[dict[str, Any]],
    target_context: dict[str, float],
    seismic_radius_km: float,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """Rank numbers by context-neighbor frequency, strongly shrunk to base scores."""
    contextual_rows = []
    for item in training_contexts:
        features = _feature_vector(item, seismic_radius_km)
        if len(set(features) & WEATHER_FEATURES) < 3:
            continue
        numbers = set(int(number) for number in item.get("numbers", []))
        if len(numbers) == PICK_COUNT:
            contextual_rows.append({"features": features, "numbers": numbers, "date": item.get("date")})

    target_weather_count = len(set(target_context) & WEATHER_FEATURES)
    if target_weather_count < 3:
        return None, {
            "ready": False,
            "reason": "La prévision météo horaire du prochain tirage contient moins de trois variables utilisables.",
            "context_training_draws": len(contextual_rows),
        }
    if len(contextual_rows) < MIN_TRAINING_DRAWS:
        return None, {
            "ready": False,
            "reason": (
                f"Il faut au moins {MIN_TRAINING_DRAWS} tirages historiques avec un contexte météo horaire complet ; "
                f"{len(contextual_rows)} sont actuellement exploitables."
            ),
            "context_training_draws": len(contextual_rows),
        }

    feature_rows = [item["features"] for item in contextual_rows]
    scales = _feature_scales(feature_rows)
    neighbors = []
    for item in contextual_rows:
        distance = _context_distance(item["features"], target_context, scales)
        if distance is None:
            continue
        neighbors.append((distance, item))
    neighbors.sort(key=lambda item: (item[0], item[1].get("date") or ""))
    selected = neighbors[: min(MAX_NEIGHBORS, len(neighbors))]
    if len(selected) < MIN_TRAINING_DRAWS:
        return None, {
            "ready": False,
            "reason": "Pas assez de contextes historiques comparables aux conditions prévues.",
            "context_training_draws": len(contextual_rows),
        }

    weights = [math.exp(-min(distance, 20.0)) for distance, _ in selected]
    weight_total = sum(weights)
    weight_square_total = sum(weight * weight for weight in weights)
    effective_neighbors = (
        weight_total * weight_total / weight_square_total if weight_square_total else 0.0
    )

    base_rows = _number_scores(training_draws)
    base_by_number = {row["number"]: float(row["score"]) for row in base_rows}
    prior = CONTEXT_PRIOR_DRAWS
    blend_weight = min(0.25, 0.12 + max(0, len(contextual_rows) - 30) * 0.0004)
    ranked = []
    for number in range(1, N_NUMBERS + 1):
        weighted_hits = sum(
            weight for weight, (_, item) in zip(weights, selected)
            if number in item["numbers"]
        )
        contextual_rate = (
            weighted_hits + prior * base_by_number[number]
        ) / (weight_total + prior)
        score = (
            (1.0 - blend_weight) * base_by_number[number]
            + blend_weight * contextual_rate
        )
        base_row = next(row for row in base_rows if row["number"] == number)
        ranked.append({
            **base_row,
            "score": score,
            "score_index": score / BASE_RATE * 100,
            "contextual_component": contextual_rate,
        })
    ranked.sort(key=lambda row: (-row["score"], row["number"]))
    diagnostics = {
        "ready": True,
        "context_training_draws": len(contextual_rows),
        "neighbors_used": len(selected),
        "effective_neighbors": round(effective_neighbors, 2),
        "blend_weight": round(blend_weight, 3),
        "features_used": sorted(set.intersection(*(set(item["features"]) for _, item in selected)) & set(target_context)),
        "mean_context_distance": round(sum(distance for distance, _ in selected) / len(selected), 3),
    }
    return ranked, diagnostics


def _upcoming_draw_date(
    latest_date: date,
    location: dict[str, Any],
    local_now: datetime | None = None,
) -> date:
    timezone_name = location.get("timezone", DEFAULT_DRAW_TIMEZONE)
    local_now = local_now or datetime.now(ZoneInfo(timezone_name))
    draw_time = datetime_time.fromisoformat(location.get("draw_time", "16:35"))
    candidate = local_now.date()
    if local_now.time().replace(tzinfo=None) >= draw_time:
        candidate += timedelta(days=1)
    return max(candidate, latest_date + timedelta(days=1))


def _context_backtest(
    draws: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    seismic_radius_km: float,
) -> dict[str, Any]:
    """Walk-forward context model comparison; each target uses its own pre-draw context."""
    by_date = {row["date"]: row for row in context_rows}
    context_hits: list[int] = []
    baseline_hits: list[int] = []
    skipped = 0
    for index in range(MIN_TRAINING_DRAWS, len(draws)):
        target = by_date.get(draws[index]["date"].isoformat())
        if not target:
            skipped += 1
            continue
        target_features = _feature_vector(target, seismic_radius_km)
        historical_contexts = [
            by_date[draw["date"].isoformat()]
            for draw in draws[:index]
            if draw["date"].isoformat() in by_date
        ]
        ranked, diagnostics = _rank_contextual(
            draws[:index],
            historical_contexts,
            target_features,
            seismic_radius_km,
        )
        if not ranked:
            skipped += 1
            continue
        actual = set(draws[index]["numbers"])
        context_hits.append(len({row["number"] for row in ranked[:PICK_COUNT]} & actual))
        baseline = _number_scores(draws[:index])
        baseline_top = {
            row["number"]
            for row in sorted(baseline, key=lambda row: (-row["score"], row["number"]))[:PICK_COUNT]
        }
        baseline_hits.append(len(baseline_top & actual))

    tested = len(context_hits)
    if not tested:
        return {
            "available": False,
            "tested_draws": 0,
            "skipped_draws": skipped,
            "expected_hits": PICK_COUNT * PICK_COUNT / N_NUMBERS,
            "reason": "Le backtest contextuel commencera dès que les historiques et prévisions météo passés seront suffisamment complets.",
        }
    level = "short" if tested < 20 else "exploratory" if tested < 40 else "monitoring"
    return {
        "available": True,
        "tested_draws": tested,
        "skipped_draws": skipped,
        "contextual_average_hits": sum(context_hits) / tested,
        "baseline_average_hits": sum(baseline_hits) / tested,
        "expected_hits": PICK_COUNT * PICK_COUNT / N_NUMBERS,
        "difference_vs_baseline": (sum(context_hits) - sum(baseline_hits)) / tested,
        "sample_level": level,
        "contextual_hit_distribution": [
            {"hits": value, "count": context_hits.count(value)}
            for value in range(PICK_COUNT + 1)
        ],
        "methodology": (
            "Validation chronologique : le contexte de chaque date cible provient des prévisions "
            "horaires à 16:00 et d'une fenêtre sismique de 24 heures se terminant au même délai "
            "avant le cutoff 16:35 que le pronostic courant. "
            "Les paramètres du modèle sont fixes ; l'ajustement contextuel est plafonné à 25 %."
        ),
        "warning": (
            "Ce résultat ne démontre pas une capacité prédictive. Un échantillon de test court "
            "doit être complété par des prévisions prospectives enregistrées avant les tirages."
        ),
    }


def _cache_key(
    draws: list[dict[str, Any]],
    target_date: date,
    seismic_lead_time: timedelta,
) -> str:
    serialized = [
        (item["date"].isoformat(), list(item["numbers"]))
        for item in draws
    ]
    location = {
        key: os.getenv(key, "")
        for key in (
            "DRAW_LOCATION_LAT", "DRAW_LOCATION_LON", "DRAW_LOCATION_NAME",
            "DRAW_LOCATION_IS_ESTIMATE", "DRAW_TIME", "DRAW_TIMEZONE",
            "SEISMIC_RADIUS_KM", "SEISMIC_MIN_MAGNITUDE",
        )
    }
    raw = json.dumps({
        "draws": serialized,
        "location": location,
        "target_date": target_date.isoformat(),
        "seismic_lead_time_bucket_15m": int(seismic_lead_time.total_seconds() // 900),
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_contextual_prediction(
    raw_draws: Iterable[dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Build an experimental contextual ranking for the next scheduled draw."""
    draws = _clean_draws(raw_draws)
    if len(draws) < MIN_TRAINING_DRAWS:
        return {
            "ready": False,
            "status": "insufficient_history",
            "reason": (
                f"Le modèle contextuel demande au moins {MIN_TRAINING_DRAWS} tirages ; "
                f"l'historique en contient {len(draws)}."
            ),
            "draw_count": len(draws),
            "minimum_draws": MIN_TRAINING_DRAWS,
            "active_weight": 0.0,
            "backtest": {
                "available": False,
                "tested_draws": 0,
                "expected_hits": PICK_COUNT * PICK_COUNT / N_NUMBERS,
                "reason": "Historique insuffisant pour l'apprentissage contextuel.",
            },
        }
    if not draws:
        return {"ready": False, "status": "no_history", "reason": "Aucun tirage enregistré."}

    location = _location_config()
    if not location.get("configured"):
        return {
            "ready": False,
            "status": "location_unavailable",
            "reason": location.get("reason") or "Lieu du tirage non configuré.",
            "draw_count": len(draws),
        }

    timezone_name = location.get("timezone", DEFAULT_DRAW_TIMEZONE)
    local_now = datetime.now(ZoneInfo(timezone_name))
    target_date = _upcoming_draw_date(draws[-1]["date"], location, local_now)
    draw_time = datetime_time.fromisoformat(location.get("draw_time", "16:35"))
    target_cutoff_local = datetime.combine(
        target_date, draw_time, tzinfo=ZoneInfo(timezone_name)
    )
    seismic_lead_time = max(target_cutoff_local - local_now, timedelta(0))
    key = _cache_key(draws, target_date, seismic_lead_time)
    now_tick = time.monotonic()
    cached = _PREDICTION_CACHE.get(key)
    if not force_refresh and cached and cached[0] > now_tick:
        return cached[1]

    try:
        historical_study = build_contextual_study(
            [{"date": item["date"], "numbers": item["numbers"]} for item in draws],
            include_all_rows=True,
            seismic_cutoff_offset=seismic_lead_time,
        )
        history_rows = sorted(historical_study.get("rows", []), key=lambda row: row["date"])
    except Exception as exc:
        return {
            "ready": False,
            "status": "historical_context_unavailable",
            "reason": "Les contextes météo/sismiques historiques n'ont pas pu être chargés.",
            "detail": type(exc).__name__,
        }

    try:
        forecast_weather = _fetch_weather_forecast(target_date, location)
    except Exception as exc:
        return {
            "ready": False,
            "status": "forecast_unavailable",
            "reason": "La prévision météo horaire du prochain tirage est indisponible.",
            "detail": type(exc).__name__,
            "next_draw_date": target_date.isoformat(),
            "historical_context_draws": len(history_rows),
        }

    future_astronomy = lunar_context(target_date, location["draw_time"], location["timezone"])
    future_row: dict[str, Any] = {
        **future_astronomy,
        "zodiac_sign": zodiac_sign(target_date),
        **forecast_weather,
    }
    try:
        seismic_snapshot = _fetch_recent_seismic_snapshot(
            location,
            as_of=local_now.astimezone(timezone.utc),
        )
        future_row.update({
            "earthquake_count": seismic_snapshot.get("earthquake_count"),
            "max_magnitude": seismic_snapshot.get("max_magnitude"),
            "nearest_distance_km": seismic_snapshot.get("nearest_distance_km"),
            "seismic_snapshot_time_utc": seismic_snapshot.get("snapshot_time_utc"),
        })
    except Exception:
        seismic_snapshot = {"available": False}
        future_row.update({
            "earthquake_count": None,
            "max_magnitude": None,
            "nearest_distance_km": None,
        })

    radius = float(location.get("seismic_radius_km", 200.0))
    target_features = _feature_vector(future_row, radius)
    by_date = {row["date"]: row for row in history_rows}
    historical_contexts = []
    for draw in draws:
        row = by_date.get(draw["date"].isoformat())
        if row:
            historical_contexts.append(row)
    ranked, diagnostics = _rank_contextual(
        draws,
        historical_contexts,
        target_features,
        radius,
    )
    if not ranked:
        result = {
            "ready": False,
            "status": "insufficient_context",
            "reason": diagnostics.get("reason"),
            "next_draw_date": target_date.isoformat(),
            "draw_count": len(draws),
            "historical_context_draws": diagnostics.get("context_training_draws", 0),
            "forecast_weather": forecast_weather,
            "seismic_snapshot": seismic_snapshot,
            "backtest": _context_backtest(draws, history_rows, radius),
        }
        _PREDICTION_CACHE[key] = (now_tick + PREDICTION_CACHE_TTL_SECONDS, result)
        return result

    backtest = _context_backtest(draws, history_rows, radius)
    top_numbers = [row["number"] for row in ranked[:PICK_COUNT]]
    features_used = diagnostics.get("features_used", [])
    result = {
        "ready": True,
        "status": "experimental_active",
        "next_draw_date": target_date.isoformat(),
        "seismic_lead_time_hours": round(seismic_lead_time.total_seconds() / 3600, 2),
        "reference_time_local": location.get("draw_time", "16:35"),
        "timezone": location.get("timezone", DEFAULT_DRAW_TIMEZONE),
        "location_name": location.get("name"),
        "location_is_estimate": location.get("location_is_estimate", False),
        "numbers": top_numbers,
        "ranked": ranked,
        "score_index": sum(row["score_index"] for row in ranked[:PICK_COUNT]) / PICK_COUNT,
        "contextual_weight": diagnostics["blend_weight"],
        "historical_context_draws": diagnostics["context_training_draws"],
        "neighbors_used": diagnostics["neighbors_used"],
        "effective_neighbors": diagnostics["effective_neighbors"],
        "mean_context_distance": diagnostics["mean_context_distance"],
        "features_used": features_used,
        "features_used_labels": sorted({FEATURE_LABELS[name] for name in features_used}),
        "forecast_weather": forecast_weather,
        "seismic_snapshot": seismic_snapshot,
        "backtest": backtest,
        "methodology": (
            "Les cinq numéros sont classés par un mélange prudent du score historique/récence "
            "et de la fréquence observée parmi les tirages passés aux contextes les plus proches. "
            "La composante contextuelle est fortement rétrécie vers le score historique et son "
            "poids est limité à 25 %. Les données astronomiques et météo sont évaluées à l'heure "
            "de référence ; la fenêtre sismique historique est alignée sur le délai du snapshot courant, "
            "et aucun événement postérieur à ce snapshot n'est utilisé. "
            "Ce modèle est expérimental et ne peut pas rendre prévisible un tirage indépendant."
        ),
        "warning": (
            "Le contexte environnemental est exploité pour construire ce classement, mais aucune "
            "influence physique sur le mécanisme du loto n'est démontrée. Suis la performance "
            "prospective contre le modèle historique et la référence de 0,714 hit/5."
        ),
    }
    if len(_PREDICTION_CACHE) >= 16:
        _PREDICTION_CACHE.pop(next(iter(_PREDICTION_CACHE)))
    _PREDICTION_CACHE[key] = (now_tick + PREDICTION_CACHE_TTL_SECONDS, result)
    return result
