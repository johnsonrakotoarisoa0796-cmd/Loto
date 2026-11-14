from datetime import date

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
