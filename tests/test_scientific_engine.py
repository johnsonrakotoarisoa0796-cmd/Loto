from datetime import date, timedelta

import pytest

from scientific_engine import (
    P_NUMBER, P_PAIR, EXPECTED_OVERLAP, _holm_adjust,
    _sum_distribution_pvalue, audit_draws,
)


def as_draws(rows):
    start = date(2025, 1, 1)
    return [{"date": start + timedelta(days=i), "numbers": sorted(values)} for i, values in enumerate(rows)]


def test_theoretical_probabilities_are_correct():
    assert P_NUMBER == pytest.approx(1 / 7)
    assert P_PAIR == pytest.approx(2 / 119)
    assert EXPECTED_OVERLAP == pytest.approx(25 / 35)


def test_small_sample_is_marked_insufficient_and_no_edge():
    draws = as_draws([
        [3, 8, 15, 19, 34], [10, 24, 25, 28, 29], [3, 12, 15, 20, 25],
        [2, 3, 16, 20, 27], [10, 13, 21, 27, 34], [14, 21, 22, 26, 34],
        [15, 18, 20, 23, 26],
    ])
    result = audit_draws(draws)
    assert result["meta"]["draw_count"] == 7
    assert result["meta"]["number_tests"] == 35
    assert result["meta"]["pair_tests"] == 595  # every possible pair is tested
    assert len(result["pair_tests"]) == 20  # only the top 20 are displayed
    assert result["meta"]["family_tests"] == 35 + 595 + 5
    assert result["status"]["level"] == "insufficient"
    assert result["status"]["exploitable_edge"] is False
    assert result["model_validation"]["available"] is False


def test_holm_is_monotone_and_never_smaller_than_raw_p():
    tests = [{"p_value": 0.001}, {"p_value": 0.03}, {"p_value": 0.02}, {"p_value": 0.8}]
    _holm_adjust(tests)
    assert all(row["p_adjusted"] >= row["p_value"] for row in tests)
    sorted_rows = sorted(tests, key=lambda row: row["p_value"])
    assert [row["p_adjusted"] for row in sorted_rows] == sorted([row["p_adjusted"] for row in sorted_rows])


def test_exact_overlap_sum_probability_is_bounded():
    p, method = _sum_distribution_pvalue(2, 3, upper=True)
    assert 0 <= p <= 1
    assert method == "convolution exacte"


def test_duplicate_dates_are_rejected():
    same = date(2026, 1, 1)
    with pytest.raises(ValueError, match="même date"):
        audit_draws([{"date": same, "numbers": [1, 2, 3, 4, 5]}, {"date": same, "numbers": [6, 7, 8, 9, 10]}])


def test_long_uniform_like_sample_does_not_claim_an_exploitable_edge():
    # Deterministic synthetic history: this tests API shape and safeguards,
    # not a power guarantee for a pseudorandom sequence.
    import random
    rng = random.Random(20261114)
    rows = [sorted(rng.sample(range(1, 36), 5)) for _ in range(260)]
    result = audit_draws(as_draws(rows))
    assert result["meta"]["draw_count"] == 260
    assert result["model_validation"]["available"] is True
    assert result["status"]["exploitable_edge"] is False or result["model_validation"]["candidate_edge"] is True


def test_deliberately_biased_series_is_flagged_but_not_declared_exploitable():
    # Synthetic positive control: a fixed subset repeated each draw.
    # It must trigger the audit while still requiring prospective confirmation.
    draws = as_draws([[1, 2, 3, 4, 5] for _ in range(260)])
    result = audit_draws(draws)
    assert result["status"]["level"] == "candidate"
    assert result["status"]["candidate_predictive_signal"] is True
    assert result["status"]["exploitable_edge"] is False
    assert result["status"]["requires_prospective_confirmation"] is True
