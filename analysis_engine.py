"""Transparent statistical analysis for a 5/35 lottery.

This module intentionally does not claim to predict a fair random draw.
It describes historical patterns, applies a strongly-shrunk ranking heuristic,
and evaluates that heuristic against the theoretical random baseline.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import random
from itertools import combinations
from math import comb, sqrt
from datetime import date
from typing import Iterable, Sequence

from scientific_engine import _forecast_hits_test, _holm_adjust

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


def build_diverse_scenarios(
    ranked: Sequence[dict],
    draws: Sequence[dict],
    count: int = 3,
    pool_size: int = 22,
    max_shared: int = 2,
) -> list[dict]:
    """Build reproducible, score-weighted alternative combinations with overlap limits.

    The primary deterministic ranking remains untouched. These scenarios are
    exploratory diversification options, not independent prediction models
    and not probability estimates. Identical history and scores yield identical
    scenarios; a changed draw history or active ranking changes the seed.
    """
    if count <= 0 or len(ranked) < PICK_COUNT:
        return []

    ordered = sorted(
        ranked,
        key=lambda row: (-float(row.get("score", row.get("score_index", 0.0))), int(row["number"])),
    )
    pool = ordered[:max(PICK_COUNT, min(int(pool_size), N_NUMBERS, len(ordered)))]
    if len(pool) < PICK_COUNT:
        return []

    numbers = [int(row["number"]) for row in pool]
    score_values = [
        max(0.0, float(row.get("score", row.get("score_index", 0.0))))
        for row in pool
    ]
    max_score = max(score_values) if score_values else 1.0
    base_weights = [
        (1.0 / ((rank + 1) ** 0.70))
        * (0.80 + 0.20 * (score / max_score if max_score > 0 else 0.0))
        for rank, score in enumerate(score_values)
    ]

    cleaned = _clean_draws(draws)
    seed_payload = {
        "draws": [
            [item["date"].isoformat(), list(item["numbers"])]
            for item in cleaned
        ],
        "ranked": [
            [int(row["number"]), round(float(row.get("score", row.get("score_index", 0.0))), 10)]
            for row in ordered
        ],
        "generator": "diverse-scenarios-v1",
    }
    seed = int(hashlib.sha256(
        json.dumps(seed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest(), 16)
    rng = random.Random(seed)

    primary = {int(row["number"]) for row in ordered[:PICK_COUNT]}
    previous: list[set[int]] = []
    usage = Counter()
    scenarios: list[dict] = []

    def weighted_sample(weights: list[float]) -> list[int]:
        available = list(range(len(numbers)))
        current_weights = list(weights)
        selected: list[int] = []
        for _ in range(PICK_COUNT):
            index = rng.choices(available, weights=current_weights, k=1)[0]
            selected.append(numbers[index])
            position = available.index(index)
            available.pop(position)
            current_weights.pop(position)
        return sorted(selected)

    for scenario_index in range(count):
        best_combo: list[int] | None = None
        best_key: tuple[float, ...] | None = None
        chosen: list[int] | None = None
        dynamic_weights = [
            weight
            * (0.65 ** usage[number])
            * (0.72 if number in primary else 1.0)
            for number, weight in zip(numbers, base_weights)
        ]

        # Rejection sampling maintains score weighting while enforcing a
        # maximum overlap of two numbers with the main and previous scenarios.
        for _ in range(1200):
            candidate = weighted_sample(dynamic_weights)
            candidate_set = set(candidate)
            if any(candidate_set == prior for prior in previous):
                continue
            overlaps = [len(candidate_set & prior) for prior in [primary, *previous]]
            mean_rank = sum(numbers.index(number) + 1 for number in candidate) / PICK_COUNT
            key = (
                float(max(overlaps, default=0)),
                float(sum(overlaps)),
                mean_rank,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_combo = candidate
            if all(overlap <= max_shared for overlap in overlaps):
                chosen = candidate
                break

        if chosen is None:
            # Keep output usable even for a pathological ranking; diagnostics
            # will make any relaxed overlap visible to the UI.
            chosen = best_combo or sorted(numbers[:PICK_COUNT])

        chosen_set = set(chosen)
        overlap_primary = len(chosen_set & primary)
        mean_rank = sum(numbers.index(number) + 1 for number in chosen) / PICK_COUNT
        scenarios.append({
            "id": f"diverse_{scenario_index + 1}",
            "label": f"Scénario diversifié {scenario_index + 1}",
            "numbers": chosen,
            "overlap_with_primary": overlap_primary,
            "mean_rank_in_pool": round(mean_rank, 1),
            "candidate_pool_size": len(pool),
            "max_allowed_overlap": max_shared,
            "diversity_constraint_met": (
                overlap_primary <= max_shared
                and all(len(chosen_set & prior) <= max_shared for prior in previous)
            ),
            "description": (
                "Sélection pondérée parmi les meilleurs rangs, avec limitation "
                "des numéros déjà présents dans les autres combinaisons."
            ),
            "score_note": (
                "Scénario exploratoire diversifié ; ce n'est ni un modèle validé "
                "ni une probabilité de gain."
            ),
        })
        previous.append(chosen_set)
        usage.update(chosen)

    return scenarios



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
    """Walk-forward comparison with exact random-null tests and Holm correction."""
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
            "minimum_confirmation_forecasts": 80,
            "confirmation_ready": False,
            "candidate_edge": False,
            "methods": [],
            "reason": (
                f"Il faut au moins {min_training + 1} tirages pour commencer "
                "la comparaison chronologique des trois méthodes."
            ),
        }

    confirmation_ready = tested_draws >= 80
    split = tested_draws // 2
    methods = []
    test_entries = []

    for definition in MODEL_DEFINITIONS:
        values = observations[definition["id"]]
        overall = _forecast_hits_test(values)
        method = {
            "id": definition["id"],
            "label": definition["label"],
            "tested_draws": len(values),
            "total_hits": overall["total_hits"],
            "average_hits": overall["mean_hits"],
            "expected_hits": overall["expected_hits"],
            "difference": overall["difference"],
            "p_value_upper": overall["p_value_upper"],
            "p_value_method": overall["p_value_method"],
            "sample_level": (
                "short" if tested_draws < 20
                else "exploratory" if tested_draws < 40
                else "monitoring"
            ),
            "note": (
                "Échantillon très court : résultat purement descriptif."
                if tested_draws < 20 else
                "Comparaison exploratoire ; pas de preuve d'un avantage prédictif."
                if tested_draws < 40 else
                "Suivi hors échantillon ; attendre deux périodes de 40 prévisions pour confirmer."
            ),
            "hit_distribution": [
                {"hits": hits, "count": values.count(hits)}
                for hits in range(PICK_COUNT + 1)
            ],
            "first_period": None,
            "confirmation_period": None,
            "confirmed_candidate": False,
        }
        overall_entry = {
            "kind": "model_overall",
            "model_id": definition["id"],
            "p_value": overall["p_value_upper"] if overall["p_value_upper"] is not None else 1.0,
        }
        test_entries.append(overall_entry)
        method["_overall_test_entry"] = overall_entry

        if confirmation_ready:
            first = _forecast_hits_test(values[:split])
            second = _forecast_hits_test(values[split:])
            for key, label, result in (
                ("first_period", "first_period", first),
                ("confirmation_period", "confirmation_period", second),
            ):
                entry = {
                    "kind": label,
                    "model_id": definition["id"],
                    "p_value": result["p_value_upper"] if result["p_value_upper"] is not None else 1.0,
                }
                test_entries.append(entry)
                method[key] = {
                    **result,
                    "tested_draws": result["forecasts"],
                    "_test_entry": entry,
                }
        methods.append(method)

    # One family-wide Holm correction covers the three overall model tests,
    # and (when available) both confirmation-period tests for every model.
    _holm_adjust(test_entries)
    candidate_models = []
    for method in methods:
        method["p_value_adjusted_holm"] = method.pop("_overall_test_entry")["p_adjusted"]
        if confirmation_ready:
            first = method["first_period"]
            second = method["confirmation_period"]
            first_entry = first.pop("_test_entry")
            second_entry = second.pop("_test_entry")
            first["p_value_adjusted_holm"] = first_entry["p_adjusted"]
            second["p_value_adjusted_holm"] = second_entry["p_adjusted"]
            method["confirmed_candidate"] = bool(
                method["difference"] > 0
                and first["difference"] > 0
                and second["difference"] > 0
                and method["p_value_adjusted_holm"] < 0.01
                and first["p_value_adjusted_holm"] < 0.05
                and second["p_value_adjusted_holm"] < 0.05
            )
        if method["confirmed_candidate"]:
            candidate_models.append(method["id"])

    return {
        "available": True,
        "training_draws": min_training,
        "tested_draws": tested_draws,
        "expected_hits": expected_overlap(),
        "minimum_confirmation_forecasts": 80,
        "confirmation_ready": confirmation_ready,
        "candidate_edge": bool(candidate_models),
        "candidate_models": candidate_models,
        "methods": methods,
        "methodology": (
            "Validation chronologique sans fuite : chaque classement est établi avant le tirage évalué. "
            "Le nombre total de numéros touchés est comparé à la distribution exacte des recouvrements "
            "entre deux combinaisons 5/35 indépendantes. Les p-values sont corrigées par Holm sur les trois "
            "méthodes ; après 80 prévisions, la correction inclut aussi deux périodes de confirmation de "
            "40 prévisions chacune."
        ),
        "confirmation_note": (
            "Deux périodes de 40 prévisions sont disponibles. Un candidat exige un écart positif dans "
            "les deux périodes, p-Holm inférieur à 1 % au total et inférieur à 5 % dans chaque période."
            if confirmation_ready else
            f"Pas de conclusion robuste avant {80} prévisions hors échantillon ; "
            f"{tested_draws} seulement sont actuellement disponibles."
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
