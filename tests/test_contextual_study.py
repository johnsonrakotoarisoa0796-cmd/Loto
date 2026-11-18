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


def test_default_location_is_explicitly_approximate_and_keeps_study_local(monkeypatch):
    monkeypatch.delenv("DRAW_LOCATION_LAT", raising=False)
    monkeypatch.delenv("DRAW_LOCATION_LON", raising=False)
    monkeypatch.delenv("DRAW_LOCATION_NAME", raising=False)
    monkeypatch.delenv("DRAW_TIMEZONE", raising=False)
    monkeypatch.setattr(
        study,
        "_external_context",
        lambda start, end, location: (
            {"weather_available": False, "seismic_available": False,
             "weather_error": None, "seismic_error": None},
            [],
        ),
    )
    result = study.build_contextual_study(_draws(7))
    assert result["meta"]["location_configured"] is True
    assert result["meta"]["location_is_estimate"] is True
    assert result["meta"]["location_name"] == "Antaninarenina, Antananarivo (approximatif)"
    assert result["meta"]["latitude"] == pytest.approx(-18.9103)
    assert result["meta"]["longitude"] == pytest.approx(47.52502)
    assert result["meta"]["timezone"] == "Indian/Antananarivo"
    assert result["meta"]["draw_time"] == "16:35"
    assert result["meta"]["timezone_assumed_utc"] is False
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
    monkeypatch.setattr(
        study,
        "_external_context",
        lambda start, end, location: (
            {"weather_available": False, "seismic_available": False,
             "weather_error": None, "seismic_error": None},
            [],
        ),
    )
    result = study.build_contextual_study(_draws(29))
    assert result["meta"]["sample_level"] == "insufficient"
    assert result["correlations"]["tests_count"] == 0
    larger = study.build_contextual_study(_draws(35))
    assert larger["meta"]["sample_level"] == "exploratory"
    assert larger["correlations"]["minimum_sample"] == study.MIN_CORRELATION_SAMPLE



def test_lunar_phase_uses_official_draw_time_and_local_timezone():
    result = study.lunar_context(
        date(2026, 11, 18),
        "16:35",
        "Indian/Antananarivo",
    )
    assert result["reference_time_local"] == "16:35"
    assert result["reference_timezone"] == "Indian/Antananarivo"
    assert result["reference_time_utc"] == "2026-11-18T13:35+00:00"
    assert result["timezone_assumed_utc"] is False


def test_draw_time_defaults_to_1635_in_madagascar_timezone(monkeypatch):
    monkeypatch.delenv("DRAW_TIME", raising=False)
    monkeypatch.delenv("DRAW_TIMEZONE", raising=False)
    draw_time, timezone_name = study._draw_time_config()
    assert draw_time.isoformat(timespec="minutes") == "16:35"
    assert timezone_name == "Indian/Antananarivo"
    result = study.lunar_context(date(2026, 11, 18), draw_time, timezone_name)
    assert result["reference_time_local"] == "16:35"
    assert result["reference_time_utc"] == "2026-11-18T13:35+00:00"
    assert result["timezone_assumed_utc"] is False

def test_custom_coordinates_override_provisional_default(monkeypatch):
    monkeypatch.setenv("DRAW_LOCATION_LAT", "-18.8792")
    monkeypatch.setenv("DRAW_LOCATION_LON", "47.5079")
    monkeypatch.setenv("DRAW_LOCATION_NAME", "Antananarivo - lieu confirmé")
    location = study._location_config()
    assert location["configured"] is True
    assert location["location_is_estimate"] is False
    assert location["latitude"] == pytest.approx(-18.8792)
    assert location["longitude"] == pytest.approx(47.5079)
    assert location["name"] == "Antananarivo - lieu confirmé"

