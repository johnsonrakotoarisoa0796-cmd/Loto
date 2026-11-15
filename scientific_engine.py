"""Scientific audit engine for fair 5/35 lottery draws.

The engine is deliberately conservative: exact null models, family-wise
multiple-testing correction, chronological out-of-sample validation, and
Bayesian shrinkage. It detects evidence inconsistent with a fair 5/35 model;
it does not claim that a future draw can be predicted.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from itertools import combinations
from math import comb, exp, lgamma, log, sqrt, erf
from typing import Iterable

N_NUMBERS = 35
PICK_COUNT = 5
P_NUMBER = PICK_COUNT / N_NUMBERS
P_PAIR = comb(PICK_COUNT, 2) / comb(N_NUMBERS, 2)  # 2/119
EXPECTED_OVERLAP = PICK_COUNT * PICK_COUNT / N_NUMBERS
PRIOR_STRENGTH = 24.0
RECENCY_HALF_LIFE = 12.0
MIN_TRAINING_DRAWS = 60
MIN_CONFIRMATION_FORECASTS = 40


def _clean_draws(raw_draws: Iterable[dict]) -> list[dict]:
    cleaned: list[dict] = []
    seen_dates: set[date] = set()
    for item in raw_draws:
        draw_date = item["date"]
        if isinstance(draw_date, str):
            draw_date = date.fromisoformat(draw_date)
        numbers = tuple(sorted(int(n) for n in item["numbers"]))
        if len(numbers) != PICK_COUNT or len(set(numbers)) != PICK_COUNT:
            raise ValueError("Chaque tirage doit contenir exactement cinq numéros distincts.")
        if any(n < 1 or n > N_NUMBERS for n in numbers):
            raise ValueError("Les numéros doivent être compris entre 1 et 35.")
        if draw_date in seen_dates:
            raise ValueError(f"Plusieurs tirages ont la même date : {draw_date.isoformat()}.")
        seen_dates.add(draw_date)
        cleaned.append({"date": draw_date, "numbers": numbers})
    return sorted(cleaned, key=lambda row: row["date"])


def _binomial_tails(n: int, p: float) -> tuple[list[float], list[float]]:
    """Stable binomial CDF and survival arrays, inclusive at each index."""
    if n < 0:
        raise ValueError("n doit être positif")
    logs = [
        lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
        + (k * log(p) if k else 0.0)
        + ((n - k) * log1p_neg(p) if n - k else 0.0)
        for k in range(n + 1)
    ]
    peak = max(logs)
    pmf = [exp(value - peak) for value in logs]
    scale = sum(pmf)
    pmf = [value / scale for value in pmf]
    cdf: list[float] = []
    running = 0.0
    for value in pmf:
        running += value
        cdf.append(min(1.0, running))
    sf = [0.0] * (n + 1)
    running = 0.0
    for k in range(n, -1, -1):
        running += pmf[k]
        sf[k] = min(1.0, running)
    return cdf, sf


def log1p_neg(p: float) -> float:
    # log(1-p), kept separate for readability and stable input range.
    from math import log1p
    return log1p(-p)


def _two_sided_binomial_p(k: int, cdf: list[float], sf: list[float]) -> float:
    # Doubled smaller inclusive tail: conservative exact two-sided p-value.
    return min(1.0, 2.0 * min(cdf[k], sf[k]))


def _holm_adjust(tests: list[dict]) -> None:
    """In-place Holm-Bonferroni adjusted p-values (valid under dependence)."""
    if not tests:
        return
    ordered = sorted(range(len(tests)), key=lambda i: tests[i]["p_value"])
    total = len(ordered)
    running = 0.0
    for rank, idx in enumerate(ordered):
        adjusted = min(1.0, (total - rank) * tests[idx]["p_value"])
        running = max(running, adjusted)
        tests[idx]["p_adjusted"] = running


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _overlap_distribution() -> list[float]:
    denominator = comb(N_NUMBERS, PICK_COUNT)
    return [
        comb(PICK_COUNT, shared) * comb(N_NUMBERS - PICK_COUNT, PICK_COUNT - shared) / denominator
        for shared in range(PICK_COUNT + 1)
    ]


_OVERLAP_PMF = _overlap_distribution()
_OVERLAP_MEAN = sum(k * probability for k, probability in enumerate(_OVERLAP_PMF))
_OVERLAP_VAR = sum((k - _OVERLAP_MEAN) ** 2 * probability for k, probability in enumerate(_OVERLAP_PMF))


def _sum_distribution_pvalue(observed: int, trials: int, upper: bool = False) -> tuple[float | None, str]:
    """P-value for a sum of iid 5/35 overlaps.

    Uses exact discrete convolution for small samples and a continuity-corrected
    normal approximation for larger samples. Overlap observations are selected
    from disjoint draw pairs, making the null observations independent.
    """
    if trials <= 0:
        return None, "indisponible"
    if trials <= 1000:
        distribution = [1.0]
        for _ in range(trials):
            nxt = [0.0] * (len(distribution) + PICK_COUNT)
            for index, mass in enumerate(distribution):
                for shared, probability in enumerate(_OVERLAP_PMF):
                    nxt[index + shared] += mass * probability
            distribution = nxt
        if upper:
            return min(1.0, sum(distribution[observed:])), "convolution exacte"
        # Probability-ordering two-sided discrete p-value.
        observed_mass = distribution[observed] if observed < len(distribution) else 0.0
        return min(1.0, sum(m for m in distribution if m <= observed_mass + 1e-15)), "convolution exacte"
    mean = trials * _OVERLAP_MEAN
    sd = sqrt(trials * _OVERLAP_VAR)
    if upper:
        z = (observed - 0.5 - mean) / sd
        return max(0.0, min(1.0, 1.0 - _normal_cdf(z))), "approximation normale corrigée"
    z = abs(observed - mean)
    z = max(0.0, (z - 0.5) / sd)
    return max(0.0, min(1.0, 2.0 * (1.0 - _normal_cdf(z)))), "approximation normale corrigée"


def _disjoint_lag_overlaps(draws: list[dict], lag: int) -> list[int]:
    """Overlaps for non-overlapping draw pairs separated by `lag` records."""
    n = len(draws)
    values: list[int] = []
    for residue in range(lag):
        left = residue
        while left + lag < n:
            right = left + lag
            values.append(len(set(draws[left]["numbers"]) & set(draws[right]["numbers"])))
            left += 2 * lag
    return values


def _scores_from_state(counts: Counter, weighted_counts: Counter, total: int, weight_total: float) -> list[dict]:
    """Rank numbers from incremental sufficient statistics."""
    prior_hits = PRIOR_STRENGTH * P_NUMBER
    rows = []
    for number in range(1, N_NUMBERS + 1):
        overall = (counts[number] + prior_hits) / (total + PRIOR_STRENGTH) if total else P_NUMBER
        recent = (weighted_counts[number] + prior_hits) / (weight_total + PRIOR_STRENGTH) if total else P_NUMBER
        score = 0.55 * overall + 0.45 * recent
        rows.append({"number": number, "score": score, "count": counts[number]})
    return sorted(rows, key=lambda row: (-row["score"], row["number"]))


def _conservative_scores(draws: list[dict]) -> list[dict]:
    """Fixed, shrinkage-heavy ranking; no tuning against the evaluation period."""
    counts: Counter = Counter()
    weighted_counts: Counter = Counter()
    decay = 2 ** (-1.0 / RECENCY_HALF_LIFE)
    weight_total = 0.0
    for draw in draws:
        for number in range(1, N_NUMBERS + 1):
            weighted_counts[number] *= decay
        weight_total *= decay
        for number in draw["numbers"]:
            counts[number] += 1
            weighted_counts[number] += 1.0
        weight_total += 1.0
    return _scores_from_state(counts, weighted_counts, len(draws), weight_total)


def _forecast_hits_test(hits: list[int]) -> dict:
    n = len(hits)
    if n == 0:
        return {"available": False, "forecasts": 0, "mean_hits": None, "expected_hits": EXPECTED_OVERLAP,
                "p_value_upper": None, "total_hits": 0}
    total_hits = sum(hits)
    p_value, method = _sum_distribution_pvalue(total_hits, n, upper=True)
    return {
        "available": True,
        "forecasts": n,
        "total_hits": total_hits,
        "mean_hits": total_hits / n,
        "expected_hits": EXPECTED_OVERLAP,
        "difference": total_hits / n - EXPECTED_OVERLAP,
        "p_value_upper": p_value,
        "p_value_method": method,
    }


def _walk_forward_validation(draws: list[dict]) -> dict:
    """Chronological OOS test. Each forecast uses only earlier draws."""
    predictions: list[int] = []
    min_train = MIN_TRAINING_DRAWS
    counts: Counter = Counter()
    weighted_counts: Counter = Counter()
    decay = 2 ** (-1.0 / RECENCY_HALF_LIFE)
    weight_total = 0.0
    for draw in draws[:min_train]:
        for number in range(1, N_NUMBERS + 1):
            weighted_counts[number] *= decay
        weight_total *= decay
        for number in draw["numbers"]:
            counts[number] += 1
            weighted_counts[number] += 1.0
        weight_total += 1.0

    for index in range(min_train, len(draws)):
        ranked = _scores_from_state(counts, weighted_counts, index, weight_total)
        predicted = {row["number"] for row in ranked[:PICK_COUNT]}
        actual = set(draws[index]["numbers"])
        predictions.append(len(predicted & actual))

        # Update only after scoring this draw: no future information leaks
        # into the prediction for the current index.
        for number in range(1, N_NUMBERS + 1):
            weighted_counts[number] *= decay
        weight_total *= decay
        for number in draws[index]["numbers"]:
            counts[number] += 1
            weighted_counts[number] += 1.0
        weight_total += 1.0

    holdout = len(predictions)
    if holdout < 2 * MIN_CONFIRMATION_FORECASTS:
        return {
            "available": False,
            "training_draws": min(min_train, len(draws)),
            "holdout_draws": holdout,
            "minimum_holdout_required": 2 * MIN_CONFIRMATION_FORECASTS,
            "expected_hits_per_forecast": EXPECTED_OVERLAP,
            "candidate_edge": False,
            "reason": (f"Validation chronologique en attente : il faut au moins {min_train} tirages d'apprentissage "
                       f"et {2 * MIN_CONFIRMATION_FORECASTS} prévisions hors échantillon, réparties en deux périodes indépendantes."),
        }

    split = holdout // 2
    first = _forecast_hits_test(predictions[:split])
    second = _forecast_hits_test(predictions[split:])
    overall = _forecast_hits_test(predictions)
    return {
        "available": True,
        "training_draws": min_train,
        "holdout_draws": holdout,
        "expected_hits_per_forecast": EXPECTED_OVERLAP,
        "overall": overall,
        "first_period": first,
        "confirmation_period": second,
        "candidate_edge": False,
        "reason": "La validation est calculée ; les p-values seront ajustées avec l'ensemble des autres tests.",
    }


def audit_draws(raw_draws: Iterable[dict]) -> dict:
    """Run a multiple-testing-controlled audit of 5/35 draw history."""
    draws = _clean_draws(raw_draws)
    n = len(draws)
    number_counts = Counter(number for draw in draws for number in draw["numbers"])
    pair_counts: Counter = Counter()
    for draw in draws:
        pair_counts.update(combinations(draw["numbers"], 2))

    tests: list[dict] = []
    number_tests: list[dict] = []
    pair_tests: list[dict] = []
    if n:
        number_cdf, number_sf = _binomial_tails(n, P_NUMBER)
        for number in range(1, N_NUMBERS + 1):
            count = number_counts[number]
            item = {
                "kind": "number",
                "number": number,
                "count": count,
                "expected_count": n * P_NUMBER,
                "rate": count / n,
                "difference": count - n * P_NUMBER,
                "p_value": _two_sided_binomial_p(count, number_cdf, number_sf),
            }
            number_tests.append(item)
            tests.append(item)

        pair_cdf, pair_sf = _binomial_tails(n, P_PAIR)
        for first, second in combinations(range(1, N_NUMBERS + 1), 2):
            count = pair_counts[(first, second)]
            item = {
                "kind": "pair",
                "numbers": [first, second],
                "count": count,
                "expected_count": n * P_PAIR,
                "p_value": _two_sided_binomial_p(count, pair_cdf, pair_sf),
            }
            pair_tests.append(item)
            tests.append(item)

    lag_tests: list[dict] = []
    for lag in range(1, 6):
        overlaps = _disjoint_lag_overlaps(draws, lag)
        observed = sum(overlaps)
        p_value, method = _sum_distribution_pvalue(observed, len(overlaps), upper=False)
        item = {
            "kind": "lag",
            "lag": lag,
            "independent_pairs": len(overlaps),
            "total_shared": observed,
            "mean_shared": observed / len(overlaps) if overlaps else None,
            "expected_mean_shared": EXPECTED_OVERLAP,
            "difference": observed / len(overlaps) - EXPECTED_OVERLAP if overlaps else None,
            "p_value": p_value if p_value is not None else 1.0,
            "p_value_method": method,
        }
        lag_tests.append(item)
        if overlaps:
            tests.append(item)

    validation = _walk_forward_validation(draws)
    model_test_rows: dict[str, dict] = {}
    if validation.get("available"):
        for key, label in (("overall", "performance globale"), ("first_period", "première période"), ("confirmation_period", "période de confirmation")):
            period = validation[key]
            if period.get("p_value_upper") is not None:
                item = {"kind": "model_validation", "label": label, "p_value": period["p_value_upper"]}
                tests.append(item)
                model_test_rows[key] = item

    _holm_adjust(tests)
    for key, item in model_test_rows.items():
        validation[key]["p_value_adjusted_global"] = item["p_adjusted"]

    if validation.get("available"):
        overall = validation["overall"]
        first = validation["first_period"]
        confirmation = validation["confirmation_period"]
        candidate = bool(
            overall.get("p_value_adjusted_global", 1.0) < 0.01
            and first.get("p_value_adjusted_global", 1.0) < 0.05
            and confirmation.get("p_value_adjusted_global", 1.0) < 0.05
            and overall.get("difference", 0.0) > 0
        )
        validation["candidate_edge"] = candidate
        validation["reason"] = (
            "Signal prédictif candidat : l'avantage dépasse le hasard après correction globale dans deux périodes chronologiques séparées. "
            "Il doit encore être confirmé prospectivement sur au moins 50 nouveaux tirages."
            if candidate else
            "Aucun avantage prédictif robuste n'est démontré après correction des comparaisons multiples. Le classement reste exploratoire."
        )

    number_tests.sort(key=lambda row: (row.get("p_adjusted", 1.0), row["number"]))
    pair_tests.sort(key=lambda row: (row.get("p_adjusted", 1.0), row["numbers"]))
    lag_tests.sort(key=lambda row: row["lag"])
    number_signals = [row for row in number_tests if row.get("p_adjusted", 1.0) < 0.05]
    pair_signals = [row for row in pair_tests if row.get("p_adjusted", 1.0) < 0.05]
    lag_signals = [row for row in lag_tests if row.get("p_adjusted", 1.0) < 0.05]
    if n < 100:
        status = "insufficient"
        headline = "Échantillon trop court pour conclure"
        explanation = "Les statistiques décrivent l'historique, mais sept ou quelques dizaines de tirages ne permettent pas de détecter de faibles biais de manière fiable."
    elif number_signals or pair_signals or lag_signals or validation.get("candidate_edge"):
        status = "candidate"
        headline = "Écart statistique à vérifier"
        explanation = "Au moins un test survit à la correction de Holm. C'est un signal à répliquer sur une période nouvelle, pas une preuve de manipulation ni une stratégie exploitable."
    else:
        status = "monitoring"
        headline = "Aucune anomalie robuste détectée"
        explanation = "Les tests ne détectent pas d'écart après correction des comparaisons multiples. Cela ne prouve pas que le mécanisme est parfaitement aléatoire."

    exploitable = bool(validation.get("candidate_edge"))
    return {
        "meta": {
            "draw_count": n,
            "first_date": draws[0]["date"].isoformat() if n else None,
            "last_date": draws[-1]["date"].isoformat() if n else None,
            "number_tests": len(number_tests),
            "pair_tests": len(pair_tests),
            "lag_tests": len([row for row in lag_tests if row["independent_pairs"]]),
            "family_tests": len(tests),
            "multiple_testing": "Holm-Bonferroni global, incluant les tests prédictifs, valable même lorsque les tests sont dépendants",
            "null_model": "Tirages indépendants et uniformes de 5 numéros distincts parmi 35, sans remise",
        },
        "status": {
            "level": status,
            "headline": headline,
            "explanation": explanation,
            "number_signals": len(number_signals),
            "pair_signals": len(pair_signals),
            "lag_signals": len(lag_signals),
            "candidate_predictive_signal": exploitable,
            "exploitable_edge": False,
            "requires_prospective_confirmation": bool(exploitable),
            "exploitation_message": (
                "Signal prédictif candidat détecté hors échantillon. Il ne sera pas déclaré exploitable avant une confirmation sur au moins 50 nouveaux tirages non utilisés pour cette analyse."
                if exploitable else
                "Aucun avantage exploitable n'est démontré. Le système surveille, mais ne transforme pas le bruit en signal."
            ),
        },
        "theory": {
            "single_number_probability": P_NUMBER,
            "pair_probability_per_draw": P_PAIR,
            "expected_shared_numbers": EXPECTED_OVERLAP,
            "probability_at_least_one_repeat": 1.0 - comb(N_NUMBERS - PICK_COUNT, PICK_COUNT) / comb(N_NUMBERS, PICK_COUNT),
            "combinations_count": comb(N_NUMBERS, PICK_COUNT),
        },
        "number_tests": number_tests,
        "pair_tests": pair_tests[:20],
        "pair_signal_details": pair_signals[:20],
        "lag_tests": lag_tests,
        "model_validation": validation,
        "methodology": [
            "35 tests de fréquence individuelle avec loi binomiale exacte marginale (p=1/7).",
            "595 tests de cooccurrence de paires avec loi binomiale exacte marginale (p=2/119).",
            "Tests de dépendance aux retards 1 à 5 sur des paires de tirages disjointes, sous loi hypergéométrique.",
            "Correction globale de Holm-Bonferroni pour limiter les faux positifs dus aux nombreux tests, y compris ceux de validation prédictive.",
            "Prévisions testées chronologiquement : chaque résultat futur est comparé à un classement construit uniquement avec le passé.",
            "Le modèle de classement utilise un lissage bayésien modéré, des paramètres fixes et aucune optimisation sur le jeu de test.",
        ],
        "limitations": [
            "Un résultat statistiquement inhabituel n'identifie pas sa cause : erreur de saisie, changement de machine, procédure ou hasard peuvent produire un écart.",
            "Aucun test fini ne prouve qu'un tirage est aléatoire ou manipulé.",
            "Aucun numéro n'est dû ; dans un système équitable, la probabilité théorique reste inchangée à chaque tirage.",
        ],
    }
