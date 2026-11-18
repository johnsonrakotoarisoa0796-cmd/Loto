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

N_NUMBERS = 35
PICK_COUNT = 5
BASE_RATE = PICK_COUNT / N_NUMBERS
PRIOR_DRAWS = 12.0
RECENT_PRIOR_DRAWS = 6.0
RECENCY_HALF_LIFE = 4.0
RECENT_SCORE_WEIGHT = 0.60
TREND_WINDOW = 5
TREND_THRESHOLD = 0.20


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
    """Return a responsive exploratory index and short-window trend indicators.

    Scores are relative ranking indices, never calibrated winning probabilities.
    Recent results receive more weight, while a moderate prior limits overreaction
    when the recorded history is short.
    """
    total = len(draws)
    if total == 0:
        return [
            {
                "number": n, "score": BASE_RATE, "overall_rate": BASE_RATE,
                "recent_rate": BASE_RATE, "count": 0, "gap": None,
                "recent_window_rate": None, "previous_window_rate": None,
                "trend_delta": None, "trend_direction": "insufficient",
                "trend_basis": "Ajoute au moins 3 tirages pour observer une tendance.",
                "trend_reliability": "insufficient", "trend_window": 0,
                "latest_draw_hit": False,
            }
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
    window = min(TREND_WINDOW, total)
    has_trend = window >= 3
    has_comparison = total >= 2 * TREND_WINDOW
    for n in range(1, N_NUMBERS + 1):
        overall = (counts[n] + PRIOR_DRAWS * BASE_RATE) / (total + PRIOR_DRAWS)
        recent = (weighted_hits[n] + RECENT_PRIOR_DRAWS * BASE_RATE) / (weight_total + RECENT_PRIOR_DRAWS)
        score = (1.0 - RECENT_SCORE_WEIGHT) * overall + RECENT_SCORE_WEIGHT * recent
        last_index = next((i for i in range(total - 1, -1, -1) if n in draws[i]["numbers"]), None)
        gap = None if last_index is None else total - 1 - last_index
        recent_window_hits = sum(n in d["numbers"] for d in draws[-window:]) if window else 0
        recent_window_rate = recent_window_hits / window if window else BASE_RATE

        if has_comparison:
            previous_window = draws[-2 * TREND_WINDOW:-TREND_WINDOW]
            previous_window_hits = sum(n in d["numbers"] for d in previous_window)
            previous_window_rate = previous_window_hits / TREND_WINDOW
            trend_delta = recent_window_rate - previous_window_rate
            trend_basis = (
                f"5 derniers : {recent_window_hits}/5 ; "
                f"5 précédents : {previous_window_hits}/5"
            )
            trend_reliability = "comparative" if total >= 20 else "provisional"
            if trend_delta >= TREND_THRESHOLD:
                trend_direction = "up"
            elif trend_delta <= -TREND_THRESHOLD:
                trend_direction = "down"
            else:
                trend_direction = "stable"
        elif has_trend:
            # With fewer than ten records, one appearance in five (20%) is
            # not enough evidence to label a number as trending up or down.
            previous_window_rate = None
            trend_delta = None
            trend_direction = "insufficient"
            trend_basis = (
                f"Signal provisoire : {recent_window_hits}/{window} apparitions récentes. "
                "La comparaison directionnelle commence après 10 tirages."
            )
            trend_reliability = "provisional"
        else:
            previous_window_rate = None
            trend_delta = None
            trend_direction = "insufficient"
            trend_basis = "Au moins 3 tirages sont nécessaires pour observer les fréquences récentes."
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
            "recent_window_hits": recent_window_hits,
            "latest_draw_hit": n in draws[-1]["numbers"],
        })
    return rows


def _top_numbers(draws: Sequence[dict]) -> list[int]:
    scores = _number_scores(draws)
    return [row["number"] for row in sorted(scores, key=lambda x: (-x["score"], x["number"]))[:PICK_COUNT]]



MODEL_DEFINITIONS = (
    {
        "id": "hybrid",
        "label": "Historique + récence",
        "description": "Équilibre les fréquences globales et les dernières sorties, avec un lissage fixe.",
    },
    {
        "id": "frequency",
        "label": "Fréquence globale lissée",
        "description": "Classe les numéros selon leur fréquence sur tout l'historique, avec un a priori modéré.",
    },
    {
        "id": "recent",
        "label": "Récence courte",
        "description": "Donne plus de poids aux tirages récents avec une demi-vie fixe de 2 tirages.",
    },
)
RECENT_MODEL_HALF_LIFE = 2.0
RECENT_MODEL_PRIOR = 8.0
BACKTEST_MIN_TRAINING_DRAWS = 30


def _method_rankings(
    draws: Sequence[dict],
    hybrid_rows: Sequence[dict] | None = None,
) -> list[dict]:
    """Build three fixed, distinct rankings; scores are indices, not probabilities."""
    total = len(draws)
    hybrid = list(hybrid_rows if hybrid_rows is not None else _number_scores(draws))
    counts = Counter(number for draw in draws for number in draw["numbers"])

    frequency_scores = {
        number: (counts[number] + PRIOR_DRAWS * BASE_RATE) / (total + PRIOR_DRAWS)
        for number in range(1, N_NUMBERS + 1)
    }

    weighted_hits: Counter = Counter()
    weight_total = 0.0
    for index, draw in enumerate(draws):
        weight = 2 ** (-(total - 1 - index) / RECENT_MODEL_HALF_LIFE)
        weight_total += weight
        for number in draw["numbers"]:
            weighted_hits[number] += weight
    recent_scores = {
        number: (weighted_hits[number] + RECENT_MODEL_PRIOR * BASE_RATE)
        / (weight_total + RECENT_MODEL_PRIOR)
        for number in range(1, N_NUMBERS + 1)
    }

    score_maps = {
        "hybrid": {row["number"]: row["score"] for row in hybrid},
        "frequency": frequency_scores,
        "recent": recent_scores,
    }
    results = []
    for definition in MODEL_DEFINITIONS:
        scores = score_maps[definition["id"]]
        ranked = sorted(
            (
                {
                    "number": number,
                    "score": scores[number],
                    "score_index": scores[number] / BASE_RATE * 100,
                }
                for number in range(1, N_NUMBERS + 1)
            ),
            key=lambda row: (-row["score"], row["number"]),
        )
        results.append({**definition, "ranked": ranked})
    return results


def _build_rank_movements(
    draws: Sequence[dict],
    current_ranked: list[dict],
) -> dict:
    """Compare today's hybrid ranking with the ranking before the latest draw."""
    if len(draws) < 2:
        return {"available": False, "up": [], "down": []}

    previous_ranked = _number_scores(draws[:-1])
    previous_rank_map = {
        row["number"]: rank
        for rank, row in enumerate(
            sorted(previous_ranked, key=lambda item: (-item["score"], item["number"])),
            start=1,
        )
    }

    rows = []
    for rank, row in enumerate(current_ranked, start=1):
        previous_rank = previous_rank_map[row["number"]]
        change = previous_rank - rank
        rows.append({
            "number": row["number"],
            "rank": rank,
            "previous_rank": previous_rank,
            "rank_change": change,
            "movement": "up" if change > 0 else "down" if change < 0 else "stable",
        })
    up = sorted((row for row in rows if row["rank_change"] > 0),
                key=lambda row: (-row["rank_change"], row["rank"]))[:5]
    down = sorted((row for row in rows if row["rank_change"] < 0),
                  key=lambda row: (row["rank_change"], row["rank"]))[:5]
    return {"available": True, "up": up, "down": down}


def _backtest_methods(
    draws: Sequence[dict],
    min_training: int = BACKTEST_MIN_TRAINING_DRAWS,
) -> dict:
    """Walk-forward comparison: each model sees only draws before the forecast."""
    observations: dict[str, list[int]] = {
        definition["id"]: [] for definition in MODEL_DEFINITIONS
    }
    for index in range(min_training, len(draws)):
        historical = draws[:index]
        actual = set(draws[index]["numbers"])
        for model in _method_rankings(historical):
            predicted = {row["number"] for row in model["ranked"][:PICK_COUNT]}
            observations[model["id"]].append(len(predicted & actual))

    tested_draws = max(0, len(draws) - min_training)
    if tested_draws == 0:
        return {
            "available": False,
            "training_draws": min_training,
            "tested_draws": 0,
            "expected_hits": expected_overlap(),
            "methods": [],
            "reason": (
                f"Il faut au moins {min_training + 1} tirages pour commencer "
                "la comparaison chronologique des trois méthodes."
            ),
        }

    methods = []
    for definition in MODEL_DEFINITIONS:
        values = observations[definition["id"]]
        average = sum(values) / len(values)
        difference = average - expected_overlap()
        if tested_draws < 20:
            sample_level = "short"
            note = "Échantillon très court : résultat purement descriptif."
        elif tested_draws < 40:
            sample_level = "exploratory"
            note = "Comparaison exploratoire ; pas de preuve d'un avantage prédictif."
        else:
            sample_level = "monitoring"
            note = "Suivi hors échantillon ; une différence passée ne garantit pas la suite."
        methods.append({
            "id": definition["id"],
            "label": definition["label"],
            "tested_draws": len(values),
            "average_hits": average,
            "expected_hits": expected_overlap(),
            "difference": difference,
            "sample_level": sample_level,
            "note": note,
            "hit_distribution": [
                {"hits": hits, "count": values.count(hits)}
                for hits in range(PICK_COUNT + 1)
            ],
        })

    return {
        "available": True,
        "training_draws": min_training,
        "tested_draws": tested_draws,
        "expected_hits": expected_overlap(),
        "methods": methods,
        "methodology": (
            "Validation chronologique : chaque méthode est recalculée avec le passé "
            "uniquement, puis comparée au tirage suivant."
        ),
    }

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
    ranked_base = sorted(number_scores, key=lambda x: (-x["score"], x["number"]))
    previous_ranks = _build_rank_movements(draws, ranked_base)
    movement_by_number = {}
    if previous_ranks["available"]:
        for row in previous_ranks["up"] + previous_ranks["down"]:
            movement_by_number[row["number"]] = row
        # Preserve stable movements for the full ranking too.
        previous_ranked = _number_scores(draws[:-1])
        previous_rank_map = {
            row["number"]: rank
            for rank, row in enumerate(
                sorted(previous_ranked, key=lambda item: (-item["score"], item["number"])),
                start=1,
            )
        }
    else:
        previous_rank_map = {}

    ranked = []
    for rank, row in enumerate(ranked_base, start=1):
        previous_rank = previous_rank_map.get(row["number"])
        rank_change = previous_rank - rank if previous_rank is not None else None
        ranked.append({
            **row,
            "rank": rank,
            "score_index": row["score"] / BASE_RATE * 100,
            "previous_rank": previous_rank,
            "rank_change": rank_change,
            "rank_movement": (
                "up" if rank_change is not None and rank_change > 0
                else "down" if rank_change is not None and rank_change < 0
                else "stable" if rank_change is not None
                else "initial"
            ),
        })

    method_rankings = _method_rankings(draws, number_scores)
    models = []
    for model in method_rankings:
        top_rows = model["ranked"][:PICK_COUNT]
        models.append({
            "id": model["id"],
            "label": model["label"],
            "description": model["description"],
            "numbers": [row["number"] for row in top_rows],
            "score_index": sum(row["score_index"] for row in top_rows) / PICK_COUNT,
            "score_note": "Indice relatif, base 100 ; ce n'est pas une probabilité.",
        })
    suggested = models[0]["numbers"]
    alternatives = [model["numbers"] for model in models[1:]]

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
            "models": models,
            "alternatives": alternatives,
            "movements": previous_ranks,
            "method": "Historique + récence : score lissé, demi-vie récente de 4 tirages.",
            "baseline_rate": BASE_RATE,
            "confidence_note": "Les indices servent à classer les numéros ; ils ne sont pas des probabilités de sortie. Un tirage équitable garde les mêmes chances théoriques à chaque date.",
        },
        "backtest": {
            **_backtest(draws),
            "methods_comparison": _backtest_methods(draws),
        },
    }
