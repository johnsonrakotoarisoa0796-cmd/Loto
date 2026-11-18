from datetime import date, timedelta

import pytest

import contextual_study as study


def _draws(count=35):
    start = date(2026, 1, 1)
    return [
        {
            "date": start + timedelta(days=index),
            "numbers": sorted({((index * 7 + offset * 5) % 35) + 1 for offset in range(5)}),
        }
        for index in range(count)
    ]


def test_zodiac_sign_uses_calendar_boundaries():
    assert study.zodiac_sign(date(2026, 1, 5)) == "Capricorne"
    assert study.zodiac_sign(date(2026, 1, 20)) == "Verseau"
    assert study.zodiac_sign(date(2026, 3, 25)) == "Bélier"
    assert study.zodiac_sign(date(2026, 12, 25)) == "Capricorne"


def test_lunar_context_is_bounded_and_has_phase_label():
    result = study.lunar_context(date(2026, 11, 18))
    assert 0 <= result["moon_illumination"] <= 1
    assert 0 <= result["moon_phase_fraction"] < 1
    assert 0 <= result["moon_age_days"] < study.SYNODIC_MONTH_DAYS
    assert result["moon_phase"] in study.MOON_PHASES


def test_study_without_coordinates_still_returns_astrology_and_astronomy(monkeypatch):
    monkeypatch.delenv("DRAW_LOCATION_LAT", raising=False)
    monkeypatch.delenv("DRAW_LOCATION_LON", raising=False)
    result = study.build_contextual_study(_draws(7))
    assert result["meta"]["location_configured"] is False
    assert result["meta"]["draw_count"] == 7
    assert len(result["rows"]) == 7
    assert all(row["zodiac_sign"] for row in result["rows"])
    assert all(row["moon_phase"] for row in result["rows"])
    assert result["meta"]["weather_available"] is False
    assert result["correlations"]["tests_count"] == 0
    assert "non validée" in result["methodology"]["astrology"]


def test_configured_study_merges_daily_weather_and_seismic_records(monkeypatch):
    monkeypatch.setenv("DRAW_LOCATION_LAT", "-18.8792")
    monkeypatch.setenv("DRAW_LOCATION_LON", "47.5079")
    monkeypatch.setenv("DRAW_LOCATION_NAME", "Antananarivo")
    monkeypatch.setenv("DRAW_TIMEZONE", "Indian/Antananarivo")
    rows = _draws(3)
    first_day = rows[0]["date"].isoformat()
    fake_weather = {
        "temperature_2m_mean": 24.0,
        "temperature_2m_max": 29.0,
        "temperature_2m_min": 19.0,
        "relative_humidity_2m_mean": 70.0,
        "pressure_msl_mean": 1012.0,
        "precipitation_sum": 2.5,
        "wind_speed_10m_max": 15.0,
        "cloud_cover_mean": 35.0,
    }
    fake_seismic = {
        "earthquake_count": 1,
        "max_magnitude": 3.2,
        "nearest_distance_km": 84.0,
        "nearest_depth_km": 12.0,
        "events": [],
    }
    monkeypatch.setattr(
        study,
        "_external_context",
        lambda start, end, location: (
            {"weather_available": True, "seismic_available": True,
             "weather_error": None, "seismic_error": None},
            [{"date": first_day, "weather": fake_weather, "seismic": fake_seismic}],
        ),
    )
    result = study.build_contextual_study(rows)
    assert result["meta"]["location_configured"] is True
    assert result["meta"]["location_name"] == "Antananarivo"
    by_date = {row["date"]: row for row in result["rows"]}
    assert by_date[first_day]["temperature_2m_mean"] == 24.0
    assert by_date[first_day]["earthquake_count"] == 1
    assert by_date[first_day]["max_magnitude"] == 3.2
    assert by_date[first_day]["nearest_depth_km"] == 12.0
    assert by_date[rows[1]["date"].isoformat()]["earthquake_count"] == 0


def test_spearman_permutation_and_holm_adjustment_are_reproducible():
    x = [float(i) for i in range(30)]
    y = [float(i * 2 + (i % 3)) for i in range(30)]
    first = study._permutation_p_value(x, y, "weather:draw_sum:30")
    second = study._permutation_p_value(x, y, "weather:draw_sum:30")
    assert first == second
    assert first[0] > 0.9
    assert 0 < first[1] <= 1

    tests = [{"p_value": 0.001}, {"p_value": 0.02}, {"p_value": 0.5}]
    study._holm_adjust(tests)
    sorted_tests = sorted(tests, key=lambda item: item["p_value"])
    adjusted = [item["p_adjusted"] for item in sorted_tests]
    assert adjusted == sorted(adjusted)
    assert all(adjusted[index] >= sorted_tests[index]["p_value"] for index in range(3))


def test_correlations_are_suppressed_when_the_predictor_is_constant():
    rows = [
        {"moon_illumination": 0.5, "draw_sum": 100 + index, "draw_range": index,
         "odd_count": 2, "low_count": 2, "overlap_previous": 1}
        for index in range(30)
    ]
    result = study._correlations(rows)
    assert result["tests_count"] == 0


def test_study_marks_small_sample_as_exploratory_or_insufficient(monkeypatch):
    monkeypatch.delenv("DRAW_LOCATION_LAT", raising=False)
    monkeypatch.delenv("DRAW_LOCATION_LON", raising=False)
    result = study.build_contextual_study(_draws(29))
    assert result["meta"]["sample_level"] == "insufficient"
    assert result["correlations"]["tests_count"] == 0
    larger = study.build_contextual_study(_draws(35))
    assert larger["meta"]["sample_level"] == "exploratory"
    assert larger["correlations"]["minimum_sample"] == study.MIN_CORRELATION_SAMPLE
