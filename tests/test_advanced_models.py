from datetime import date, timedelta

from advanced_models import METHOD_DEFINITIONS, build_advanced_rankings


def _draws(rows):
    start = date(2026, 1, 1)
    return [
        {"date": start + timedelta(days=index), "numbers": numbers}
        for index, numbers in enumerate(rows)
    ]


def test_four_advanced_methods_return_full_valid_rankings():
    rows = [[(index * 3 + offset * 7) % 35 + 1 for offset in range(5)] for index in range(45)]
    models = build_advanced_rankings(_draws(rows))

    assert [model["id"] for model in models] == [item["id"] for item in METHOD_DEFINITIONS]
    assert len(models) == 4
    for model in models:
        ranked = model["ranked"]
        assert len(ranked) == 35
        assert {row["number"] for row in ranked} == set(range(1, 36))
        assert len({row["number"] for row in ranked[:5]}) == 5
        assert all(0 < row["score"] < 1 for row in ranked)
        assert all(row["score_index"] > 0 for row in ranked)
        assert model["ready"] is True


def test_advanced_models_react_to_persistent_next_draw_associations():
    rows = [[1, 2, 3, 4, 5] for _ in range(60)]
    models = build_advanced_rankings(_draws(rows))

    for model in models:
        assert [row["number"] for row in model["ranked"][:5]] == [1, 2, 3, 4, 5]


def test_short_history_is_flagged_and_scores_remain_shrunk():
    rows = [[1, 7, 14, 21, 35] for _ in range(8)]
    models = build_advanced_rankings(_draws(rows))

    assert all(model["ready"] is False for model in models)
    assert all(model["diagnostics"]["usable"] is False for model in models)
    assert all(
        0 < row["score"] < 1
        for model in models
        for row in model["ranked"]
    )


def test_empty_history_returns_neutral_rankings_without_failing():
    models = build_advanced_rankings([])

    assert len(models) == 4
    assert all(model["ready"] is False for model in models)
    assert all(len(model["ranked"]) == 35 for model in models)
    assert all(
        abs(row["score"] - (5 / 35)) < 1e-12
        for model in models
        for row in model["ranked"]
    )
