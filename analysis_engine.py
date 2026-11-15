"""Transparent statistical analysis for a 5/35 lottery.

This module intentionally does not claim to predict a fair random draw.
It describes historical patterns, applies a strongly-shrunk ranking heuristic,
and evaluates that heuristic against the theoretical random baseline.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from math import comb, sqrt
from datetime import date
from typing import Iterable, Sequence
import random

N_NUMBERS = 35
PICK_COUNT = 5
BASE_RATE = PICK_COUNT / N_NUMBERS
PRIOR_DRAWS = 24.0
RECENCY_HALF_LIFE = 12.0


def _clean_draws(draws: Iterable[dict]) -> list[dict]:
    cleaned = []
    for item in draws:
        draw_date = item["date"]
        if isinstance(draw_date, str):
            draw_date = date.fromisoformat(draw_date)
        numbers = tuple(sorted(int(n) for n in item["numbers"]))
        if len(numbers) != PICK_COUNT or len(set(numbers)) != PICK_COUNT:
            raise ValueError("Chaque tirage doit contenir exactement 5 numéros distincts.")
        if any(n < 1 or n > N_NUMBERS for n in numbers):
            raise ValueError("Les numéros doivent être compris entre 1 et 35.")
        cleaned.append({"date": draw_date, "numbers": numbers})
    cleaned.sort(key=lambda x: x["date"])
    return cleaned


def theoretical_overlap_probability() -> float:
    """P(at least one shared number in two independent 5-of-35 draws)."""
    return 1.0 - comb(N_NUMBERS - PICK_COUNT, PICK_COUNT) / comb(N_NUMBERS, PICK_COUNT)


def expected_overlap() -> float:
    return PICK_COUNT * PICK_COUNT / N_NUMBERS


def _number_scores(draws: Sequence[dict]) -> list[dict]:
    """Return smoothed historical rates; not calibrated winning probabilities."""
    total = len(draws)
    if total == 0:
        return [
            {"number": n, "score": BASE_RATE, "overall_rate": BASE_RATE,
             "recent_rate": BASE_RATE, "count": 0, "gap": None}
            for n in range(1, N_NUMBERS + 1)
        ]

    counts = Counter(n for d in draws for n in d["numbers"])
    weights = [2 ** (-(total - 1 - i) / RECENCY_HALF_LIFE) for i in range(total)]
    weight_total = sum(weights)
    weighted_hits = Counter()
    for draw, weight in zip(draws, weights):
        for n in draw["numbers"]:
            weighted_hits[n] += weight

    rows = []
    for n in range(1, N_NUMBERS + 1):
        # A 70-draw prior centered on the fair-lottery marginal rate prevents
        # small samples from producing exaggerated "hot number" estimates.
        overall = (counts[n] + PRIOR_DRAWS * BASE_RATE) / (total + PRIOR_DRAWS)
        recent = (weighted_hits[n] + PRIOR_DRAWS * BASE_RATE) / (weight_total + PRIOR_DRAWS)
        score = 0.55 * overall + 0.45 * recent
        last_index = next((i for i in range(total - 1, -1, -1) if n in draws[i]["numbers"]), None)
        gap = None if last_index is None else total - 1 - last_index

        # Compare a recent window with the preceding window when possible.
        # Before 20 draws, compare with the theoretical 1/7 rate and mark it provisional.
        window = min(10, total)
        if window >= 5:
            recent_window = draws[-window:]
            recent_window_rate = sum(n in d["numbers"] for d in recent_window) / window
            if total >= 2 * window:
                previous_window = draws[-2 * window:-window]
                previous_window_rate = sum(n in d["numbers"] for d in previous_window) / window
                trend_delta = recent_window_rate - previous_window_rate
                trend_basis = f"{window} derniers tirages comparés aux {window} précédents"
                trend_reliability = "comparative"
            else:
                previous_window_rate = None
                trend_delta = recent_window_rate - BASE_RATE
                trend_basis = f"Signal provisoire : {window} derniers tirages comparés à la référence théorique de 14,29 %"
                trend_reliability = "provisional"
            if trend_delta > 0.05:
                trend_direction = "up"
            elif trend_delta < -0.05:
                trend_direction = "down"
            else:
                trend_direction = "stable"
        else:
            recent_window_rate = sum(n in d["numbers"] for d in draws) / total
            previous_window_rate = None
            trend_delta = None
            trend_direction = "insufficient"
            trend_basis = "Au moins 5 tirages sont nécessaires pour afficher une tendance provisoire."
            trend_reliability = "insufficient"

        rows.append({
            "number": n,
            "score": score,
            "overall_rate": counts[n] / total,
            "recent_rate": weighted_hits[n] / weight_total,
            "count": counts[n],
            "gap": gap,
            "recent_window_rate": recent_window_rate,
            "previous_window_rate": previous_window_rate,
            "trend_delta": trend_delta,
            "trend_direction": trend_direction,
            "trend_basis": trend_basis,
            "trend_reliability": trend_reliability,
            "trend_window": window,
        })
    return rows


def _top_numbers(draws: Sequence[dict]) -> list[int]:
    scores = _number_scores(draws)
    return [row["number"] for row in sorted(scores, key=lambda x: (-x["score"], x["number"]))[:PICK_COUNT]]


def _backtest(draws: Sequence[dict], min_training: int = 60) -> dict:
    observations = []
    for i in range(min_training, len(draws)):
        predicted = set(_top_numbers(draws[:i]))
        actual = set(draws[i]["numbers"])
        observations.append(len(predicted & actual))
    if not observations:
        return {
            "available": False,
            "reason": f"Il faut au moins {min_training + 1} tirages pour tester les prédictions sans regarder le futur.",
            "tested_draws": 0,
            "model_average_hits": None,
            "random_expected_hits": expected_overlap(),
            "model_hit_distribution": [],
        }
    wins = sum(x > expected_overlap() for x in observations)
    return {
        "available": True,
        "tested_draws": len(observations),
        "model_average_hits": sum(observations) / len(observations),
        "random_expected_hits": expected_overlap(),
        "model_better_than_baseline_count": wins,
        "model_equal_or_worse_count": len(observations) - wins,
        "model_hit_distribution": [
            {"hits": k, "count": observations.count(k)} for k in range(PICK_COUNT + 1)
        ],
        "warning": "Un petit historique de test ne permet pas de démontrer un avantage prédictif.",
    }


def analyze_draws(raw_draws: Iterable[dict]) -> dict:
    draws = _clean_draws(raw_draws)
    total = len(draws)
    number_scores = _number_scores(draws)
    counts = Counter(n for d in draws for n in d["numbers"])
    expected_count = total * BASE_RATE
    frequency_rows = []
    for row in number_scores:
        count = counts[row["number"]]
        std = sqrt(total * BASE_RATE * (1 - BASE_RATE)) if total else 0.0
        z = (count - expected_count) / std if std else 0.0
        frequency_rows.append({
            **row,
            "expected_count": expected_count,
            "difference": count - expected_count,
            "z_score_descriptive": z,
        })

    transitions = []
    daily_transitions = []
    pair_counts: Counter = Counter()
    for draw in draws:
        pair_counts.update(combinations(draw["numbers"], 2))
    for previous, current in zip(draws, draws[1:]):
        shared = sorted(set(previous["numbers"]) & set(current["numbers"]))
        delta_days = (current["date"] - previous["date"]).days
        item = {
            "from_date": previous["date"].isoformat(),
            "to_date": current["date"].isoformat(),
            "shared_numbers": shared,
            "shared_count": len(shared),
            "calendar_days_apart": delta_days,
            "is_next_calendar_day": delta_days == 1,
        }
        transitions.append(item)
        if delta_days == 1:
            daily_transitions.append(item)

    daily_repeats = sum(bool(t["shared_numbers"]) for t in daily_transitions)
    successive_repeats = sum(bool(t["shared_numbers"]) for t in transitions)
    overlap_histogram = [
        {"shared": k, "count": sum(t["shared_count"] == k for t in transitions)}
        for k in range(PICK_COUNT + 1)
    ]

    reappearance = []
    for n in range(1, N_NUMBERS + 1):
        opportunities = sum(n in d["numbers"] for d in [x for x in draws[:-1]])
        returned = sum(n in previous["numbers"] and n in current["numbers"]
                       for previous, current in zip(draws, draws[1:]))
        reappearance.append({
            "number": n,
            "opportunities": opportunities,
            "returned_next_record": returned,
            "rate": returned / opportunities if opportunities else None,
        })

    pairs = [
        {"numbers": [a, b], "count": count}
        for (a, b), count in pair_counts.most_common(15)
    ]
    ranked = sorted(number_scores, key=lambda x: (-x["score"], x["number"]))
    suggested = [x["number"] for x in ranked[:PICK_COUNT]]
    alternatives = []
    rng = random.Random(f"loto-5-35-{total}-{draws[-1]['date'].isoformat() if total else 'empty'}")
    # Alternative sets are for exploration, not better-odds combinations.
    pool = ranked[:18] if total else ranked
    weights = [max(0.001, row["score"]) for row in pool]
    for _ in range(2):
        chosen = set()
        while len(chosen) < PICK_COUNT:
            candidate = rng.choices(pool, weights=weights, k=1)[0]["number"]
            chosen.add(candidate)
        alternatives.append(sorted(chosen))

    transitions_total = len(transitions)
    overlap_p = theoretical_overlap_probability()
    # Exact one-sided binomial tail for the daily transition repeat count.
    n_daily = len(daily_transitions)
    tail = None
    if n_daily:
        tail = sum(comb(n_daily, k) * overlap_p**k * (1 - overlap_p)**(n_daily-k)
                   for k in range(daily_repeats, n_daily + 1))

    return {
        "summary": {
            "draw_count": total,
            "latest_date": draws[-1]["date"].isoformat() if total else None,
            "earliest_date": draws[0]["date"].isoformat() if total else None,
            "unique_numbers_seen": sum(counts[n] > 0 for n in range(1, N_NUMBERS + 1)),
            "daily_transition_count": n_daily,
            "daily_repeat_count": daily_repeats,
            "daily_repeat_rate": daily_repeats / n_daily if n_daily else None,
            "theoretical_repeat_probability": overlap_p,
            "theoretical_repeat_percent": overlap_p * 100,
            "average_shared_numbers": (sum(t["shared_count"] for t in daily_transitions) / n_daily) if n_daily else None,
            "expected_shared_numbers": expected_overlap(),
            "successive_transition_count": transitions_total,
            "successive_repeat_count": successive_repeats,
            "successive_repeat_rate": successive_repeats / transitions_total if transitions_total else None,
            "daily_repeat_binomial_tail": tail,
        },
        "frequencies": frequency_rows,
        "transitions": transitions[-30:][::-1],
        "overlap_histogram": overlap_histogram,
        "reappearance": sorted(reappearance, key=lambda x: (
            x["rate"] is None, -(x["rate"] or 0), -x["opportunities"], x["number"]
        )),
        "frequent_pairs": pairs,
        "prediction": {
            "numbers": suggested,
            "ranked": ranked,
            "alternatives": alternatives,
            "method": "Fréquence historique + pondération récente, fortement lissées vers 1/7.",
            "baseline_rate": BASE_RATE,
            "confidence_note": "Indice exploratoire, pas une probabilité de gain. Si le tirage est équitable et indépendant, chaque numéro conserve 1 chance sur 7 à chaque tirage.",
        },
        "backtest": _backtest(draws),
    }
