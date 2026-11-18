from datetime import date, timedelta

import pytest

import contextual_predictor as predictor


def _rows(count=40):
    start = date(2026, 1, 1)
    draws = []
    contexts = []
    for index in range(count):
        numbers = sorted({((index * 5 + offset * 7) % 35) + 1 for offset in range(5)})
        draws.append({"date": start + timedelta(days=index), "numbers": numbers})
        contexts.append({
            "date": (start + timedelta(days=index)).isoformat(),
            "numbers": numbers,
            "moon_phase_fraction": (index % 29) / 29,
            "zodiac_sign": "Lion" if index % 12 == 0 else "Vierge",
            "temperature_2m_at_draw_hour": 20.0 + (index % 2) * 5,
            "relative_humidity_2m_at_draw_hour": 65.0 + (index % 3) * 5,
            "pressure_msl_at_draw_hour": 1010.0 + (index % 4),
            "precipitation_at_draw_hour": (index % 3) * 0.1,
            "wind_speed_10m_at_draw_hour": 8.0 + (index % 5),
            "cloud_cover_at_draw_hour": 25.0 + (index % 6) * 10,
            "earthquake_count": index % 2,
            "max_magnitude": 3.0 if index % 2 else 0.0,
            "nearest_distance_km": 80.0 if index % 2 else 200.0,
        })
    return draws, contexts


def test_contextual_model_returns_a_valid_shrunk_ranking():
    draws, contexts = _rows(40)
    target = {
        "moon_phase_fraction": 0.4,
        "zodiac_sign": "Lion",
        "temperature_2m_at_draw_hour": 25.0,
        "relative_humidity_2m_at_draw_hour": 75.0,
        "pressure_msl_at_draw_hour": 1012.0,
        "precipitation_at_draw_hour": 0.1,
        "wind_speed_10m_at_draw_hour": 10.0,
        "cloud_cover_at_draw_hour": 45.0,
        "earthquake_count": 1,
        "max_magnitude": 3.0,
        "nearest_distance_km": 80.0,
    }
    features = predictor._feature_vector(target, 200.0)
    ranked, diagnostics = predictor._rank_contextual(draws, contexts, features, 200.0)

    assert diagnostics["ready"] is True
    assert len(ranked) == 35
    assert len({row["number"] for row in ranked[:5]}) == 5
    assert 0 < diagnostics["blend_weight"] <= 0.25
    assert diagnostics["neighbors_used"] >= predictor.MIN_TRAINING_DRAWS
    assert all(row["score_index"] > 0 for row in ranked)


def test_contextual_model_requires_enough_hourly_weather_features():
    draws, contexts = _rows(40)
    target = {
        "moon_phase_fraction": 0.4,
        "zodiac_sign": "Lion",
        "temperature_2m_at_draw_hour": 25.0,
        "relative_humidity_2m_at_draw_hour": 75.0,
    }
    ranked, diagnostics = predictor._rank_contextual(
        draws,
        contexts,
        predictor._feature_vector(target, 200.0),
        200.0,
    )
    assert ranked is None
    assert diagnostics["ready"] is False
    assert "météo horaire" in diagnostics["reason"]


def test_contextual_prediction_refuses_to_learn_from_a_tiny_history():
    start = date(2026, 11, 1)
    draws = [
        {"date": start + timedelta(days=index), "numbers": [1, 7, 14, 21, 35]}
        for index in range(7)
    ]
    result = predictor.build_contextual_prediction(draws)
    assert result["ready"] is False
    assert result["status"] == "insufficient_history"
    assert result["active_weight"] == 0.0
    assert result["minimum_draws"] == 30


def test_same_context_has_zero_distance_and_different_context_is_separated():
    draws, contexts = _rows(40)
    first = predictor._feature_vector(contexts[0], 200.0)
    second = predictor._feature_vector(contexts[1], 200.0)
    scales = predictor._feature_scales([first, second])
    assert predictor._context_distance(first, first, scales) == pytest.approx(0.0)
    distance = predictor._context_distance(first, second, scales)
    assert distance is not None
    assert distance > 0

def test_context_backtest_compares_contextual_model_and_historical_baseline():
    draws, contexts = _rows(42)
    result = predictor._context_backtest(draws, contexts, 200.0)
    assert result["available"] is True
    assert result["tested_draws"] == 12
    assert result["contextual_average_hits"] >= 0
    assert result["baseline_average_hits"] >= 0
    assert result["expected_hits"] == pytest.approx(25 / 35)
    assert result["sample_level"] == "short"

