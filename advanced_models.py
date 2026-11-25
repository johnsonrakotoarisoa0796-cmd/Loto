"""Regularised experimental ranking models for the 5/35 lottery.

The methods are descriptive candidates, not calibrated winning probabilities.
Every function uses only the supplied draw prefix; walk-forward evaluation must
call it with the prefix available before each target draw.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

N_NUMBERS = 35
PICK_COUNT = 5
BASE_RATE = PICK_COUNT / N_NUMBERS
MIN_TRAINING_DRAWS = 30

GAP_PRIOR_STRENGTH = 180.0
MARKOV_PRIOR_STRENGTH = 50.0
PAIR_PRIOR_STRENGTH = 60.0
WINDOW_PRIOR_STRENGTH = 10.0

METHOD_DEFINITIONS = (
    {
        "id": "gap_hazard",
        "label": "Retards · risque de retour lissé",
        "description": (
            "Estime le taux de retour par tranche de retard, avec un fort "
            "lissage vers 1/7 pour éviter de traiter un numéro comme « dû »."
        ),
    },
    {
        "id": "markov",
        "label": "Markov · transition à un tirage",
        "description": (
            "Estime la sortie au tirage suivant selon la présence ou l'absence "
            "du numéro au tirage précédent, avec régularisation forte."
        ),
    },
    {
        "id": "pair_transition",
        "label": "Associations entre tirages · pair-lift",
        "description": (
            "Mesure les associations ordonnées entre chaque numéro du dernier "
            "tirage et les numéros du tirage enregistré suivant, avec lissage."
        ),
    },
    {
        "id": "multi_window",
        "label": "Fréquences multi-fenêtres",
        "description": (
            "Moyenne à poids fixe des fréquences lissées sur 5, 10, 20 tirages "
            "et sur l'historique complet."
        ),
    },
)


def _number_sets(draws: Sequence[dict[str, Any]]) -> list[set[int]]:
    result: list[set[int]] = []
    for draw in draws:
        numbers = {int(number) for number in draw["numbers"]}
        if len(numbers) != PICK_COUNT or any(number < 1 or number > N_NUMBERS for number in numbers):
            raise ValueError("Chaque tirage doit contenir 5 numéros distincts compris entre 1 et 35.")
        result.append(numbers)
    return result


def _gap_bucket(gap: int) -> str:
    return str(gap) if gap <= 3 else "4+"


def _rank(scores: dict[int, float]) -> list[dict[str, float | int]]:
    return [
        {
            "number": number,
            "score": scores[number],
            "score_index": scores[number] / BASE_RATE * 100.0,
        }
        for number in sorted(scores, key=lambda number: (-scores[number], number))
    ]


def _gap_hazard_scores(sets: Sequence[set[int]]) -> tuple[dict[int, float], dict[str, Any]]:
    """Pool next-draw hit rates by current gap, then shrink each bucket to 1/7."""
    exposures: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    last_seen: dict[int, int] = {}

    for index in range(max(0, len(sets) - 1)):
        for number in sets[index]:
            last_seen[number] = index
        next_draw = sets[index + 1]
        for number in range(1, N_NUMBERS + 1):
            previous_index = last_seen.get(number)
            gap = index - previous_index if previous_index is not None else index + 1
            bucket = _gap_bucket(gap)
            exposures[bucket] += 1
            hits[bucket] += int(number in next_draw)

    current_gaps: dict[int, int] = {}
    current_buckets: Counter[str] = Counter()
    last_seen = {}
    for index, draw in enumerate(sets):
        for number in draw:
            last_seen[number] = index
    last_index = len(sets) - 1
    for number in range(1, N_NUMBERS + 1):
        previous_index = last_seen.get(number)
        gap = last_index - previous_index if previous_index is not None else len(sets)
        current_gaps[number] = gap
        current_buckets[_gap_bucket(gap)] += 1

    bucket_rates = {
        bucket: (hits[bucket] + GAP_PRIOR_STRENGTH * BASE_RATE)
        / (exposures[bucket] + GAP_PRIOR_STRENGTH)
        for bucket in ("0", "1", "2", "3", "4+")
    }
    scores = {
        number: bucket_rates[_gap_bucket(current_gaps[number])]
        for number in range(1, N_NUMBERS + 1)
    }
    diagnostics = {
        "bucket_exposures": {bucket: exposures[bucket] for bucket in ("0", "1", "2", "3", "4+")},
        "bucket_hits": {bucket: hits[bucket] for bucket in ("0", "1", "2", "3", "4+")},
        "current_numbers_by_bucket": dict(current_buckets),
        "prior_strength": GAP_PRIOR_STRENGTH,
        "minimum_training_draws": MIN_TRAINING_DRAWS,
        "usable": len(sets) >= MIN_TRAINING_DRAWS,
    }
    return scores, diagnostics


def _markov_scores(sets: Sequence[set[int]]) -> tuple[dict[int, float], dict[str, Any]]:
    """Estimate P(number at t+1 | number at t), with a beta prior centred at 1/7."""
    exposures = {0: 0, 1: 0}
    hits = {0: 0, 1: 0}
    for previous, current in zip(sets, sets[1:]):
        for number in range(1, N_NUMBERS + 1):
            state = int(number in previous)
            exposures[state] += 1
            hits[state] += int(number in current)

    latest = sets[-1] if sets else set()
    state_rates = {
        state: (hits[state] + MARKOV_PRIOR_STRENGTH * BASE_RATE)
        / (exposures[state] + MARKOV_PRIOR_STRENGTH)
        for state in (0, 1)
    }
    scores = {
        number: state_rates[int(number in latest)]
        for number in range(1, N_NUMBERS + 1)
    }
    diagnostics = {
        "state_exposures": {str(state): exposures[state] for state in (0, 1)},
        "state_hits": {str(state): hits[state] for state in (0, 1)},
        "current_state_counts": {"present": len(latest), "absent": N_NUMBERS - len(latest)},
        "prior_strength": MARKOV_PRIOR_STRENGTH,
        "minimum_training_draws": MIN_TRAINING_DRAWS,
        "usable": len(sets) >= MIN_TRAINING_DRAWS,
    }
    return scores, diagnostics


def _pair_transition_scores(sets: Sequence[set[int]]) -> tuple[dict[int, float], dict[str, Any]]:
    """Average regularised next-draw association scores from the latest five numbers."""
    pair_hits: Counter[tuple[int, int]] = Counter()
    source_exposures: Counter[int] = Counter()
    for previous, current in zip(sets, sets[1:]):
        for source in previous:
            source_exposures[source] += 1
            for target in current:
                pair_hits[(source, target)] += 1

    latest = sets[-1] if sets else set()
    scores: dict[int, float] = {}
    if not latest:
        scores = {number: BASE_RATE for number in range(1, N_NUMBERS + 1)}
    else:
        for target in range(1, N_NUMBERS + 1):
            conditional_rates = [
                (pair_hits[(source, target)] + PAIR_PRIOR_STRENGTH * BASE_RATE)
                / (source_exposures[source] + PAIR_PRIOR_STRENGTH)
                for source in latest
            ]
            scores[target] = sum(conditional_rates) / len(conditional_rates)

    diagnostics = {
        "latest_source_numbers": sorted(latest),
        "source_exposures": {str(number): source_exposures[number] for number in sorted(latest)},
        "prior_strength": PAIR_PRIOR_STRENGTH,
        "minimum_training_draws": MIN_TRAINING_DRAWS,
        "usable": len(sets) >= MIN_TRAINING_DRAWS,
    }
    return scores, diagnostics


def _multi_window_scores(sets: Sequence[set[int]]) -> tuple[dict[int, float], dict[str, Any]]:
    """Equal-weight, prior-smoothed frequency average over fixed lookback windows."""
    total = len(sets)
    windows = sorted({min(window, total) for window in (5, 10, 20, total) if min(window, total) > 0})
    if not windows:
        windows = [0]

    per_window: dict[str, dict[int, float]] = {}
    for window in windows:
        recent = sets[-window:] if window else []
        counts = Counter(number for draw in recent for number in draw)
        prior = max(WINDOW_PRIOR_STRENGTH, float(window))
        per_window[str(window)] = {
            number: (counts[number] + prior * BASE_RATE) / (window + prior)
            for number in range(1, N_NUMBERS + 1)
        }

    scores = {
        number: sum(per_window[str(window)][number] for window in windows) / len(windows)
        for number in range(1, N_NUMBERS + 1)
    }
    diagnostics = {
        "windows": windows,
        "prior_strength": WINDOW_PRIOR_STRENGTH,
        "minimum_training_draws": MIN_TRAINING_DRAWS,
        "usable": len(sets) >= MIN_TRAINING_DRAWS,
    }
    return scores, diagnostics


def build_advanced_rankings(draws: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return four separate candidate rankings, never silently activating one."""
    sets = _number_sets(draws)
    methods = (
        ("gap_hazard", _gap_hazard_scores(sets)),
        ("markov", _markov_scores(sets)),
        ("pair_transition", _pair_transition_scores(sets)),
        ("multi_window", _multi_window_scores(sets)),
    )
    definitions = {item["id"]: item for item in METHOD_DEFINITIONS}
    results = []
    for method_id, (scores, diagnostics) in methods:
        definition = definitions[method_id]
        results.append({
            **definition,
            "ranked": _rank(scores),
            "diagnostics": diagnostics,
            "ready": bool(diagnostics["usable"]),
            "score_note": "Indice relatif lissé, base 100 ; ce n'est pas une probabilité de sortie.",
        })
    return results
