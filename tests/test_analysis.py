from datetime import date, timedelta

import pytest

from analysis_engine import analyze_draws, expected_overlap, theoretical_overlap_probability


SAMPLE = [
    (date(2026, 11, 8), [3, 8, 15, 19, 34]),
    (date(2026, 11, 9), [10, 24, 25, 28, 29]),
    (date(2026, 11, 10), [3, 12, 15, 20, 25]),
    (date(2026, 11, 11), [2, 3, 16, 20, 27]),
    (date(2026, 11, 12), [10, 13, 21, 27, 34]),
    (date(2026, 11, 13), [14, 21, 22, 26, 34]),
    (date(2026, 11, 14), [15, 18, 20, 23, 26]),
]


def as_dict(items=SAMPLE):
    return [{"date": day, "numbers": numbers} for day, numbers in items]


def test_theoretical_overlap_baseline():
    assert theoretical_overlap_probability() == pytest.approx(0.561, abs=0.001)
    assert expected_overlap() == pytest.approx(25 / 35)


def test_user_sample_repeat_analysis():
    result = analyze_draws(as_dict())
    summary = result["summary"]
    assert summary["draw_count"] == 7
    assert summary["daily_transition_count"] == 6
    assert summary["daily_repeat_count"] == 5
    assert summary["daily_repeat_rate"] == pytest.approx(5 / 6)
    assert summary["unique_numbers_seen"] == 22


def test_hot_number_counts_match_sample():
    result = analyze_draws(as_dict())
    counts = {row["number"]: row["count"] for row in result["frequencies"]}
    assert counts[3] == 3
    assert counts[15] == 3
    assert counts[20] == 3
    assert counts[34] == 3


def test_gaps_between_dates_are_not_counted_as_daily_pairs():
    sparse = [SAMPLE[0], SAMPLE[1], SAMPLE[3]]
    result = analyze_draws(as_dict(sparse))
    assert result["summary"]["successive_transition_count"] == 2
    assert result["summary"]["daily_transition_count"] == 1


def test_empty_history_has_safe_baseline():
    result = analyze_draws([])
    assert result["summary"]["draw_count"] == 0
    assert len(result["frequencies"]) == 35
    assert len(result["prediction"]["numbers"]) == 5
    assert result["backtest"]["available"] is False


def test_invalid_draw_is_rejected():
    bad = [{"date": date(2026, 11, 1), "numbers": [1, 1, 2, 3, 4]}]
    with pytest.raises(ValueError):
        analyze_draws(bad)



def test_prediction_exposes_three_fixed_and_distinct_models():
    result = analyze_draws(as_dict())
    models = result["prediction"]["models"]
    assert [model["id"] for model in models] == ["hybrid", "frequency", "recent"]
    for model in models:
        assert len(model["numbers"]) == 5
        assert len(set(model["numbers"])) == 5
        assert all(1 <= number <= 35 for number in model["numbers"])
        assert model["score_index"] > 0
    assert result["prediction"]["numbers"] == models[0]["numbers"]
    assert result["prediction"]["alternatives"] == [models[1]["numbers"], models[2]["numbers"]]


def test_recent_and_global_frequency_methods_can_react_differently():
    rows = [[1, 2, 3, 4, 5] for _ in range(25)]
    rows.extend([[6, 7, 8, 9, 10] for _ in range(5)])
    models = analyze_draws(as_dict([
        (date(2026, 1, 1) + timedelta(days=i), row)
        for i, row in enumerate(rows)
    ]))["prediction"]["models"]
    frequency = next(model for model in models if model["id"] == "frequency")
    recent = next(model for model in models if model["id"] == "recent")
    assert frequency["numbers"] == [1, 2, 3, 4, 5]
    assert recent["numbers"] == [6, 7, 8, 9, 10]


def test_rank_movements_compare_latest_ranking_to_previous_draw():
    rows = [[2, 3, 4, 5, 6] for _ in range(10)]
    after = analyze_draws(as_dict([
        (date(2026, 1, 1) + timedelta(days=i), row)
        for i, row in enumerate(rows + [[1, 7, 8, 9, 10]])
    ]))
    number_one = next(row for row in after["prediction"]["ranked"] if row["number"] == 1)
    assert number_one["rank_change"] is not None
    assert number_one["rank_change"] > 0
    assert after["prediction"]["movements"]["available"] is True
    assert any(row["number"] == 7 for row in after["prediction"]["movements"]["up"])


def test_methods_backtest_is_walk_forward_and_reports_random_baseline():
    rows = [[(i + j) % 35 + 1 for j in range(5)] for i in range(40)]
    result = analyze_draws(as_dict([
        (date(2026, 1, 1) + timedelta(days=i), row)
        for i, row in enumerate(rows)
    ]))
    comparison = result["backtest"]["methods_comparison"]
    assert comparison["available"] is True
    assert comparison["training_draws"] == 30
    assert comparison["tested_draws"] == 10
    assert comparison["expected_hits"] == pytest.approx(25 / 35)
    assert [row["id"] for row in comparison["methods"]] == ["hybrid", "frequency", "recent"]
    assert all(row["tested_draws"] == 10 for row in comparison["methods"])
    assert all(row["sample_level"] == "short" for row in comparison["methods"])


def test_methods_backtest_waits_until_one_draw_after_training():
    rows = [[1, 2, 3, 4, 5] for _ in range(30)]
    result = analyze_draws(as_dict([
        (date(2026, 1, 1) + timedelta(days=i), row)
        for i, row in enumerate(rows)
    ]))
    comparison = result["backtest"]["methods_comparison"]
    assert comparison["available"] is False
    assert comparison["tested_draws"] == 0
    assert "31" in comparison["reason"]
