from datetime import date, timedelta

from analysis_engine import analyze_draws


def _draws(rows):
    start = date(2026, 1, 1)
    return [
        {"date": start + timedelta(days=index), "numbers": sorted(numbers)}
        for index, numbers in enumerate(rows)
    ]


def _ranked(result, number):
    return next(row for row in result["prediction"]["ranked"] if row["number"] == number)


def test_score_changes_when_a_new_draw_is_added():
    rows = [
        [3, 8, 15, 19, 34], [10, 24, 25, 28, 29], [3, 12, 15, 20, 25],
        [2, 3, 16, 20, 27], [10, 13, 21, 27, 34], [14, 21, 22, 26, 34],
        [15, 18, 20, 23, 26],
    ]
    before = analyze_draws(_draws(rows))
    after = analyze_draws(_draws(rows + [[1, 2, 3, 4, 5]]))
    before_scores = {row["number"]: row["score"] for row in before["prediction"]["ranked"]}
    after_scores = {row["number"]: row["score"] for row in after["prediction"]["ranked"]}
    assert any(abs(before_scores[n] - after_scores[n]) > 1e-6 for n in range(1, 36))


def test_latest_draw_hit_has_a_visible_effect_on_that_number_score():
    rows = [[2, 3, 4, 5, 6] for _ in range(10)]
    before = analyze_draws(_draws(rows))
    after = analyze_draws(_draws(rows + [[1, 7, 8, 9, 10]]))
    assert _ranked(after, 1)["score"] > _ranked(before, 1)["score"] + 0.01
    assert _ranked(after, 1)["latest_draw_hit"] is True


def test_recent_trend_compares_last_five_with_previous_five():
    rows = [[2, 3, 4, 5, 6] for _ in range(20)]
    rows[-2:] = [[1, 2, 3, 4, 5] for _ in range(2)]
    number_one = _ranked(analyze_draws(_draws(rows)), 1)
    assert number_one["trend_direction"] == "up"
    assert number_one["trend_reliability"] == "comparative"
    assert number_one["trend_window"] == 5
    assert number_one["trend_delta"] > 0


def test_one_new_hit_changes_a_stable_trend_immediately():
    rows = [[2, 3, 4, 5, 6] for _ in range(10)]
    before = analyze_draws(_draws(rows))
    after = analyze_draws(_draws(rows + [[1, 7, 8, 9, 10]]))
    assert _ranked(before, 1)["trend_direction"] == "stable"
    assert _ranked(after, 1)["trend_direction"] == "up"
    assert _ranked(after, 1)["trend_delta"] == 0.2
    assert _ranked(after, 1)["trend_reliability"] == "provisional"


def test_short_history_marks_recent_trend_as_provisional():
    rows = [
        [1, 2, 3, 4, 5], [2, 3, 4, 5, 6], [2, 3, 4, 5, 6],
        [2, 3, 4, 5, 6], [2, 3, 4, 5, 6], [2, 3, 4, 5, 6],
        [2, 3, 4, 5, 6],
    ]
    number_one = _ranked(analyze_draws(_draws(rows)), 1)
    assert number_one["trend_reliability"] == "provisional"
    assert "provisoire" in number_one["trend_basis"].lower()



def test_short_history_shows_recent_count_without_false_up_signal():
    rows = [
        [2, 3, 4, 5, 6], [2, 3, 4, 5, 6], [2, 3, 4, 5, 6],
        [1, 7, 8, 9, 10], [2, 3, 4, 5, 6], [2, 3, 4, 5, 6],
        [2, 3, 4, 5, 6],
    ]
    row = _ranked(analyze_draws(_draws(rows)), 1)
    assert row["recent_window_hits"] == 1
    assert row["trend_direction"] == "insufficient"
    assert row["trend_delta"] is None
    assert row["trend_reliability"] == "provisional"
