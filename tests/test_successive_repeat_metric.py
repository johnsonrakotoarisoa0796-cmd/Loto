from datetime import date

from analysis_engine import analyze_draws


def test_next_draw_repeat_rate_uses_all_successive_recorded_draws():
    draws = [
        {"date": date(2026, 1, 1), "numbers": [1, 2, 3, 4, 5]},
        {"date": date(2026, 1, 2), "numbers": [1, 6, 7, 8, 9]},
        # A skipped calendar day must not remove this pair from the next-draw KPI.
        {"date": date(2026, 1, 4), "numbers": [10, 11, 12, 13, 14]},
        {"date": date(2026, 1, 6), "numbers": [10, 15, 16, 17, 18]},
    ]

    summary = analyze_draws(draws)["summary"]

    assert summary["successive_transition_count"] == 3
    assert summary["successive_repeat_count"] == 2
    assert summary["successive_repeat_rate"] == 2 / 3

    # Calendar-day repetition remains a separate statistic.
    assert summary["daily_transition_count"] == 1
    assert summary["daily_repeat_count"] == 1
    assert summary["daily_repeat_rate"] == 1.0
